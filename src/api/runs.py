"""Run status/detail and history endpoints (spec/api.md).

Supersedes the skeleton's `transform_text` demo endpoints — the CSV Insight
Agent's real product surface is `POST /sessions/{id}/messages` (starts a
run) plus these read endpoints, not a generic `/runs` create route.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import Dataset, Run
from db.session import get_session


def _parse_iso(value: str, field: str) -> datetime:
    """Parse an ISO date or datetime string into a timezone-aware datetime.

    Accepts a plain date (``2026-07-01``) or a full ISO datetime, with or
    without a trailing ``Z``. Naive values are assumed UTC so the comparison
    against the timezone-aware ``created_at`` column is well-defined.
    """
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise api_error(
            "INVALID_DATE", f"{field} must be an ISO date or datetime: {value!r}", 400
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

router = APIRouter()


def _run_detail(run: Run) -> dict:
    base: dict = {"run_id": run.id, "status": run.status}

    if run.status in ("pending", "running"):
        base.update(
            {
                "step_count": run.step_count,
                "total_estimated_steps": run.total_estimated_steps,
                "current_step_label": None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
            }
        )
        return base

    if run.status == "needs_clarification":
        base["clarification_question"] = run.clarification_question
        return base

    if run.status == "failed":
        base.update(
            {
                "stuck_explanation": run.stuck_explanation,
                "generated_code": run.generated_code,
                "retry_count": run.retry_count,
            }
        )
        return base

    # completed
    base.update(
        {
            "question_text": run.question_text,
            "answer_text": run.answer_text,
            "key_numbers": run.key_numbers_json,
            "chart_spec": run.chart_spec_json,
            "table_data": run.table_data_json,
            "generated_code": run.generated_code,
            "assumptions": run.assumptions_json or [],
            "anomalies": run.anomalies_json or [],
            "retry_count": run.retry_count,
            "step_count": run.step_count,
            "total_estimated_steps": run.total_estimated_steps,
            "token_input_count": run.token_input_count,
            "token_output_count": run.token_output_count,
            "estimated_cost_usd": float(run.estimated_cost_usd)
            if run.estimated_cost_usd is not None
            else 0.0,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
    )
    return base


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(Run, run_id)
    if run is None:
        raise api_error("NOT_FOUND", f"Run {run_id} not found", 404)
    return ok(_run_detail(run))


@router.get("/runs")
def list_runs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: Session = Depends(get_session),
) -> dict:
    query = session.query(Run)

    if q and q.strip():
        # Case-insensitive substring search on the question text. SQLAlchemy's
        # ilike() emits a dialect-safe case-insensitive LIKE; escape LIKE
        # wildcards in the user's term so they match literally.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(Run.question_text.ilike(f"%{term}%", escape="\\"))

    if date_from is not None and date_from.strip():
        query = query.filter(Run.created_at >= _parse_iso(date_from, "date_from"))

    if date_to is not None and date_to.strip():
        query = query.filter(Run.created_at <= _parse_iso(date_to, "date_to"))

    runs = (
        query
        .order_by(Run.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    dataset_ids = {r.dataset_id for r in runs}
    datasets = (
        {d.id: d for d in session.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()}
        if dataset_ids
        else {}
    )
    return ok(
        [
            {
                "run_id": r.id,
                "dataset_filename": datasets[r.dataset_id].filename
                if r.dataset_id in datasets
                else None,
                "question_text": r.question_text,
                "status": r.status,
                "estimated_cost_usd": float(r.estimated_cost_usd)
                if r.estimated_cost_usd is not None
                else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]
    )
