"""Session / message endpoints (spec/api.md).

`POST /sessions/{id}/messages` starts a `Run` (spec/agent.md's ask-a-question
graph) in the background and returns immediately; the frontend polls
`GET /runs/{run_id}` (src/api/runs.py) for progress and the final result.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from api._common import api_error, ok
from db.models import Dataset, Message, Run
from db.models import Session as SessionModel
from db.session import get_session
from graph.runner import start_run

router = APIRouter()

_ACTIVE_RUN_STATUSES = ("pending", "running")


class MessageRequest(BaseModel):
    content: str = ""


class SessionRequest(BaseModel):
    dataset_id: str


@router.post("/sessions")
def create_session(
    req: SessionRequest, session: OrmSession = Depends(get_session)
) -> dict:
    """Start a new session against an already-profiled dataset (reselect flow).

    Requires the dataset to exist and be `parsed` — an unparsed dataset has
    no usable profile to back a conversation (spec/api.md Phase 2).
    """
    dataset = session.get(Dataset, req.dataset_id)
    if dataset is None or dataset.status != "parsed":
        raise api_error(
            "NOT_FOUND", f"Dataset {req.dataset_id} not found or not parsed.", 404
        )

    new_session = SessionModel(dataset_id=dataset.id)
    session.add(new_session)
    session.flush()
    return ok({"session_id": new_session.id, "dataset_id": dataset.id})


@router.post("/sessions/{session_id}/messages")
def post_message(
    session_id: str, req: MessageRequest, session: OrmSession = Depends(get_session)
) -> dict:
    sess = session.get(SessionModel, session_id)
    if sess is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)

    if not req.content or not req.content.strip():
        raise api_error("EMPTY_CONTENT", "content must not be empty.", 400)

    if not sess.dataset_id:
        raise api_error("NO_DATASET", "This session has no attached dataset.", 400)

    existing = (
        session.query(Run)
        .filter(Run.session_id == session_id, Run.status.in_(_ACTIVE_RUN_STATUSES))
        .first()
    )
    if existing is not None:
        raise api_error(
            "RUN_IN_PROGRESS", "A run is already in progress for this session.", 409
        )

    session.add(Message(session_id=session_id, role="user", content=req.content))

    run = Run(
        session_id=session_id,
        dataset_id=sess.dataset_id,
        question_text=req.content,
        status="running",
    )
    session.add(run)
    session.flush()
    run_id = run.id
    dataset_id = sess.dataset_id
    # Commit now (rather than waiting for the get_session dependency's
    # post-route commit) so the background thread's independent DB session
    # can see this Run row immediately.
    session.commit()

    start_run(run_id, session_id, dataset_id, req.content)

    return ok({"run_id": run_id, "status": "running"})


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str, session: OrmSession = Depends(get_session)) -> dict:
    sess = session.get(SessionModel, session_id)
    if sess is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)

    messages = (
        session.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return ok(
        [
            {
                "role": m.role,
                "content": m.content,
                "run_id": m.run_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
    )
