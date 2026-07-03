from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Numeric, Text, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid import uuid4


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    """Legacy skeleton table for the (now-superseded) `transform_text` capability.

    Kept as-is (untouched schema/table name "runs") because src/api/runs.py,
    src/graph/runner.py, and several existing tests still reference it directly.
    The CSV Insight Agent's real run audit-trail entity is `Run` below, mapped
    to a differently-named table ("insight_runs") specifically to avoid a
    table-name collision with this legacy row — see the `Run` class docstring.
    Removal of this legacy model belongs to the slice(s) that own
    src/api/*` and `src/graph/*`, not to db-schema.
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class Dataset(Base):
    """One uploaded CSV file and its precomputed profile (spec/data.md).

    Immutable once successfully parsed — a re-upload creates a new row.
    """

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-column profile: {name: {dtype, null_count, null_pct, distinct_count, min, max, mean, std}}
    schema_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # List of {column, type, severity, description}
    anomalies_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # "uploaded" | "parsed" | "needs_decision" | "failed"
    status: Mapped[str] = mapped_column(Text, nullable=False, default="uploaded")
    parse_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class Session(Base):
    """One browser visit's working context: the active dataset and its conversation."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    # Nullable to allow a session to exist briefly before a dataset is attached.
    dataset_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("datasets.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    last_active_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class Message(Base):
    """One turn of the conversation (user question or assistant reply)."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    # "user" | "assistant" | "system"
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Set on assistant messages that resulted from a run.
    run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("insight_runs.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class Run(Base):
    """One full audit-trail record of a single question being answered (spec/data.md).

    NOTE: mapped to table "insight_runs", not "runs" — the skeleton's legacy
    `RunRow` model already owns the "runs" table for the (superseded)
    transform_text capability, and several existing files outside this
    slice's ownership (src/api/runs.py, src/graph/runner.py, and their
    tests) still reference it directly. Renaming/removing that legacy table
    is out of scope for db-schema; import the `Run` class by name from
    db.models rather than assuming a specific table name.
    """

    __tablename__ = "insight_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(Text, ForeignKey("datasets.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # "pending" | "running" | "needs_clarification" | "completed" | "failed"
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_numbers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chart_spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    table_data_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    anomalies_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stuck_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_estimated_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_output_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=0
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class RunStep(Base):
    """One entry in a run's step-by-step audit trail."""

    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("insight_runs.id"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # load_context | classify_request | ask_clarification | generate_code |
    # execute_code | observe_and_decide | show_stuck_point | finalize
    step_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    code_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
