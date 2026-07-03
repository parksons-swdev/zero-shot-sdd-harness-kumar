"""Wires the ask-a-question LangGraph (`graph.agent.agentic_ai`) to the real
DB and the real dataset DataFrame, per the dependency-injection contract
documented atop `graph/agent.py` (spec/agent.md, spec/api.md).

`start_run` is called by `api.sessions.post_message` once a `Run` row has
already been created (status="running") and committed. It runs the graph in
a background thread so the API can return `{run_id, status: "running"}`
immediately per spec/api.md's polling model; the caller polls
`GET /runs/{run_id}` for progress/completion.
"""

from __future__ import annotations

import threading

import pandas as pd

from db.models import Dataset, Message, Run, RunStep, _now
from db.session import create_db_session
from graph.agent import agentic_ai
from observability.events import get_logger
from tools.ingestion import ParsedCsv, parse_csv

log = get_logger("runner")

_MAX_HISTORY_TURNS = 10
_DEFAULT_TOTAL_ESTIMATED_STEPS = 5


def _load_dataframe(dataset_id: str) -> pd.DataFrame:
    """`dataframe_loader` injection point (see graph/agent.py docstring)."""
    with create_db_session() as db:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise RuntimeError(f"Dataset {dataset_id} not found")
        file_path = dataset.file_path

    parsed = parse_csv(file_path)
    if isinstance(parsed, ParsedCsv):
        return parsed.df
    raise RuntimeError(f"Dataset {dataset_id} could not be re-parsed for analysis: {parsed.issue}")


def _load_context(dataset_id: str, session_id: str) -> dict:
    """`context_loader` injection point (see graph/agent.py docstring)."""
    with create_db_session() as db:
        dataset = db.get(Dataset, dataset_id)
        messages = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in messages][-_MAX_HISTORY_TURNS:]
        return {
            "dataset_schema": (dataset.schema_json if dataset else None) or {},
            "dataset_anomalies": (dataset.anomalies_json if dataset else None) or [],
            "conversation_history": history,
        }


def _apply_state_to_run(db, run: Run, state: dict) -> None:
    """Copies a final `AnalysisState` onto a `Run` row + writes its
    `RunStep` audit trail and assistant `Message` (spec/data.md). Shared by
    the graph's own `persist_fn` and by `_execute`'s fallback sync below.
    """
    run.status = state.get("status", "failed")
    run.clarification_question = state.get("clarification_question")
    run.assumptions_json = state.get("assumptions") or []
    run.generated_code = state.get("generated_code")
    run.answer_text = state.get("answer_text")
    run.key_numbers_json = state.get("key_numbers")
    run.chart_spec_json = state.get("chart_spec")
    run.table_data_json = state.get("table_data")
    run.anomalies_json = state.get("dataset_anomalies") or []
    run.stuck_explanation = state.get("stuck_explanation")
    run.retry_count = max(state.get("attempt_count", 0) - 1, 0)
    run.step_count = state.get("step_count", 0)
    run.total_estimated_steps = (
        state.get("total_estimated_steps") or run.step_count or _DEFAULT_TOTAL_ESTIMATED_STEPS
    )
    token_usage = state.get("token_usage") or {}
    run.token_input_count = token_usage.get("input_tokens", 0)
    run.token_output_count = token_usage.get("output_tokens", 0)
    run.estimated_cost_usd = state.get("estimated_cost_usd", 0.0) or 0.0
    run.error_message = state.get("error")
    run.completed_at = _now()

    for step in state.get("steps", []):
        db.add(
            RunStep(
                run_id=run.id,
                step_number=step["step_number"],
                step_type=step["step_type"],
                label=step["label"],
                code_snippet=step.get("code_snippet"),
                is_error=step.get("is_error", False),
                output_summary=step.get("output_summary"),
            )
        )

    answer_text = state.get("answer_text")
    if answer_text:
        db.add(
            Message(
                session_id=state["session_id"],
                role="assistant",
                content=answer_text,
                run_id=run.id,
            )
        )


def _persist_final_state(state: dict) -> str:
    """`persist_fn` injection point (see graph/agent.py docstring).

    Writes the `Run` row, its `RunStep` audit trail, and the assistant
    `Message` row. Raising here is treated as fatal per spec/agent.md.
    """
    run_id = state["run_id"]
    with create_db_session() as db:
        run = db.get(Run, run_id)
        if run is None:
            raise RuntimeError(f"Run {run_id} vanished during execution")
        _apply_state_to_run(db, run, state)

    return run_id


def _mark_failed(run_id: str, error: str) -> None:
    with create_db_session() as db:
        run = db.get(Run, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = error
            run.completed_at = _now()


def _execute(run_id: str, session_id: str, dataset_id: str, question: str) -> None:
    try:
        initial_state = {
            "run_id": run_id,
            "session_id": session_id,
            "dataset_id": dataset_id,
            "question": question,
            "dataframe_loader": _load_dataframe,
            "context_loader": _load_context,
            "persist_fn": _persist_final_state,
            "total_estimated_steps": _DEFAULT_TOTAL_ESTIMATED_STEPS,
        }
        final_state = agentic_ai.invoke(initial_state)
    except Exception as exc:  # noqa: BLE001 - framework-level fatal failure
        log.error("run_execution_failed", run_id=run_id, error=str(exc))
        _mark_failed(run_id, str(exc))
        return

    # Per spec/agent.md's fixed graph topology, a fatal error in
    # `load_context`/`classify_request`/`generate_code` routes straight to
    # `handle_error` -> END, which NEVER passes through `persist_run` (and
    # therefore never calls `persist_fn`). Without this fallback the Run row
    # would stay "running" forever and GET /runs/{id} would poll endlessly.
    # This sync is idempotent: if `persist_run` already ran, the row is no
    # longer "pending"/"running" and this is a no-op.
    with create_db_session() as db:
        run = db.get(Run, run_id)
        if run is not None and run.status in ("pending", "running"):
            _apply_state_to_run(db, run, final_state)


def start_run(run_id: str, session_id: str, dataset_id: str, question: str) -> None:
    """Kicks off graph execution in a background thread; returns immediately."""
    thread = threading.Thread(
        target=_execute, args=(run_id, session_id, dataset_id, question), daemon=True
    )
    thread.start()
