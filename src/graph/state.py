from typing import Any, Callable, TypedDict


class AnalysisState(TypedDict, total=False):
    """State for the ask-a-question LangGraph agent (spec/agent.md).

    Non-persisted, dependency-injection keys (not part of the spec's
    canonical schema, but part of this graph's public contract — see the
    module docstring in `graph/agent.py` for how a caller wires these):

    - dataframe_loader: Callable[[str], pandas.DataFrame] — given
      `dataset_id`, returns the full DataFrame for that dataset. Required
      unless a DataFrame has already been placed in the in-process cache
      by a previous call in the same process.
    - context_loader: Callable[[str, str], dict] — given
      (dataset_id, session_id), returns
      {"dataset_schema": ..., "dataset_anomalies": ..., "conversation_history": ...}.
      Optional: if `dataset_schema` etc. are already present in the initial
      state, `load_context` will not call this.
    - persist_fn: Callable[[AnalysisState], str] — given the final state,
      performs the actual DB write (Run/RunStep/Message rows) and returns
      the `run_id`. If omitted, `persist_run` is a local no-op (useful for
      testing the graph in isolation).
    """

    # Identity
    run_id: str
    session_id: str
    dataset_id: str

    # Input
    question: str
    conversation_history: list[dict]
    dataset_schema: dict
    dataset_anomalies: list[dict]

    # Uncertainty handling (priority order: clarify > best-guess+flag > show-stuck > retry)
    clarification_needed: bool
    clarification_question: str | None
    assumptions: list[str]

    # Reasoning loop
    plan: str | None
    generated_code: str | None
    code_attempts: list[dict]
    attempt_count: int
    max_attempts: int
    execution_result: dict | None
    execution_full_result: dict | None
    execution_error: str | None
    stuck: bool
    stuck_explanation: str | None

    # Progress / observability
    steps: list[dict]
    step_count: int
    total_estimated_steps: int
    token_usage: dict
    estimated_cost_usd: float

    # Output
    answer_text: str | None
    key_numbers: dict | None
    chart_spec: dict | None
    table_data: list[dict] | None

    # Control
    status: str
    error: str | None

    # Dependency injection (not persisted; see class docstring and
    # graph/agent.py's module docstring for the full contract)
    dataframe_loader: Callable[[str], Any]
    context_loader: Callable[[str, str], dict] | None
    persist_fn: Callable[[dict], str] | None

    # Internal/transient (set by observe_and_decide, read by after_observe;
    # never persisted, never sent to an LLM)
    _sufficient: bool


# Backward-compat alias: the skeleton's legacy `transform_text` pipeline
# (`src/graph/runner.py`, `src/api/runs.py`, and their tests — owned by the
# `api-routes` slice, not this one) still imports `AgentState` by name.
# TypedDict has no runtime field enforcement, so this alias keeps those
# modules importable without reintroducing the old single-node graph here.
# That legacy pipeline is functionally superseded by this graph; cleaning up
# its remaining references is `api-routes`'s responsibility.
AgentState = AnalysisState
