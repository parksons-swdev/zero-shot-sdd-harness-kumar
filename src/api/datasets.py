"""Dataset upload / profile / decision endpoints (spec/api.md).

Wraps the deterministic dataset-ingestion pipeline (`tools.ingestion`,
`tools.profiling`) with real disk storage and a `Dataset` DB row. No LLM
calls happen here — parsing/profiling is fully deterministic.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api._common import api_error, ok
from config.settings import get_settings
from db.models import Dataset, Session as SessionModel
from db.session import get_session
from domain.dataset import DatasetProfile, ParseDecision
from tools.ingestion import CHOICE_REUPLOAD, CHOICE_SKIP_BAD_LINES, ParsedCsv, parse_csv
from tools.profiling import build_dataset_profile

router = APIRouter()


class DecisionRequest(BaseModel):
    choice: str


def _dataset_response(dataset: Dataset) -> dict:
    return {
        "dataset_id": dataset.id,
        "status": dataset.status,
        "filename": dataset.filename,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "schema": dataset.schema_json or [],
        "anomalies": dataset.anomalies_json or [],
    }


def _needs_decision_response(dataset: Dataset, decision: ParseDecision) -> dict:
    return {
        "dataset_id": dataset.id,
        "status": "needs_decision",
        "issue": decision.issue,
        "choices": decision.choices,
    }


def _apply_parsed(dataset: Dataset, profile: DatasetProfile) -> None:
    profile_dict = profile.to_dict()
    dataset.status = "parsed"
    dataset.row_count = profile.row_count
    dataset.column_count = profile.column_count
    dataset.schema_json = profile_dict["schema"]
    dataset.anomalies_json = profile_dict["anomalies"]
    dataset.parse_warnings = profile.parse_warnings


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...), session: Session = Depends(get_session)
) -> dict:
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise api_error("INVALID_FILE", "Only .csv files are accepted.", 400)

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    dataset_id = str(uuid4())
    dest_path = upload_dir / f"{dataset_id}.csv"

    size = 0
    try:
        with open(dest_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    dest_path.unlink(missing_ok=True)
                    raise api_error(
                        "FILE_TOO_LARGE",
                        f"File exceeds the {settings.max_upload_mb}MB limit.",
                        400,
                    )
                out.write(chunk)
    except OSError as exc:
        dest_path.unlink(missing_ok=True)
        raise api_error("DISK_ERROR", f"Could not write uploaded file: {exc}", 500) from exc

    if size == 0:
        dest_path.unlink(missing_ok=True)
        raise api_error("INVALID_FILE", "The uploaded file is empty.", 400)

    dataset = Dataset(
        id=dataset_id,
        filename=file.filename,
        file_path=str(dest_path),
        size_bytes=size,
        status="uploaded",
    )
    session.add(dataset)
    session.flush()

    try:
        parsed = parse_csv(str(dest_path))
    except Exception as exc:  # noqa: BLE001 - defensive; parse_csv itself never raises
        raise api_error("PARSE_ERROR", f"Unexpected parsing failure: {exc}", 500) from exc

    if isinstance(parsed, ParseDecision):
        dataset.status = "needs_decision"
        session.flush()
        return ok(_needs_decision_response(dataset, parsed))

    profile = build_dataset_profile(parsed)
    _apply_parsed(dataset, profile)
    session.flush()

    new_session = SessionModel(dataset_id=dataset.id)
    session.add(new_session)
    session.flush()

    response = _dataset_response(dataset)
    response["session_id"] = new_session.id
    return ok(response)


@router.post("/datasets/{dataset_id}/decisions")
def resolve_decision(
    dataset_id: str, req: DecisionRequest, session: Session = Depends(get_session)
) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None or dataset.status != "needs_decision":
        raise api_error(
            "NOT_FOUND", f"Dataset {dataset_id} not found or not awaiting a decision.", 404
        )

    if req.choice not in (CHOICE_SKIP_BAD_LINES, CHOICE_REUPLOAD):
        raise api_error("INVALID_CHOICE", f"Unknown choice: {req.choice!r}", 400)

    if req.choice == CHOICE_REUPLOAD:
        # This endpoint resolves an existing file in place; re-uploading a
        # different file goes through POST /datasets, not here. Dataset
        # stays in `needs_decision` with the same choices until the client
        # follows up with a fresh upload.
        return ok(
            _needs_decision_response(
                dataset,
                ParseDecision(
                    issue="Please upload a different file via POST /datasets.",
                    choices=[CHOICE_SKIP_BAD_LINES, CHOICE_REUPLOAD],
                ),
            )
        )

    parsed = parse_csv(dataset.file_path, skip_bad_lines=True)
    if isinstance(parsed, ParseDecision):
        return ok(_needs_decision_response(dataset, parsed))

    profile = build_dataset_profile(parsed)
    _apply_parsed(dataset, profile)
    session.flush()
    return ok(_dataset_response(dataset))


@router.get("/datasets")
def list_datasets(session: Session = Depends(get_session)) -> dict:
    """Recent, reselectable datasets — reverse-chronological.

    Only `parsed` datasets appear: a dataset in `uploaded`, `needs_decision`,
    or `failed` state has no usable profile and cannot back a new session.
    """
    datasets = (
        session.query(Dataset)
        .filter(Dataset.status == "parsed")
        .order_by(Dataset.created_at.desc())
        .all()
    )
    return ok(
        [
            {
                "dataset_id": d.id,
                "filename": d.filename,
                "row_count": d.row_count,
                "created_at": d.created_at.isoformat(),
            }
            for d in datasets
        ]
    )


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)
    return ok(_dataset_response(dataset))
