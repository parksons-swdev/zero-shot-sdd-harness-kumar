"""The ask-a-question LangGraph assembly (spec/agent.md → Graph Assembly).

This graph is PURE reasoning/execution logic — it has NO database
dependency. It is invoked with a plain `AnalysisState` dict and returns a
plain `AnalysisState` dict. Three keys in the initial state are the
dependency-injection points for the caller (the `api-routes` slice, in
practice):

    dataframe_loader: Callable[[str], pandas.DataFrame]
        REQUIRED (unless the dataset's DataFrame is already warm in this
        process's `graph.nodes._dataframe_cache`). Given `dataset_id`,
        must return the full, real DataFrame for that dataset (e.g. by
        reading `Dataset.file_path` and `pd.read_csv(...)`). Called at most
        once per `dataset_id` per process — the result is cached in-process
        by `load_context`.

    context_loader: Callable[[str, str], dict] | None
        OPTIONAL. Given `(dataset_id, session_id)`, must return
        `{"dataset_schema": dict, "dataset_anomalies": list[dict],
        "conversation_history": list[dict]}` — e.g. read from the `Dataset`
        row's `schema_json`/`anomalies_json` and the session's recent
        `Message` rows. Only called if `dataset_schema` /
        `dataset_anomalies` / `conversation_history` are not already present
        in the initial state (a caller may instead pre-load these itself
        and skip this callback entirely).

    persist_fn: Callable[[AnalysisState], str] | None
        OPTIONAL. Given the complete final state, must write the `Run` row,
        `RunStep` audit-trail rows, and the assistant `Message` row (per
        `spec/data.md`), and return the `run_id`. If omitted, `persist_run`
        is a local no-op — useful for testing the graph without a database.
        A raising `persist_fn` is treated as fatal: `persist_run` sets
        `state["status"] = "failed"` and `state["error"]` (the fixed graph
        topology below routes `persist_run` straight to `END` either way,
        per spec/agent.md's literal Graph Assembly code — callers should
        check `final_state["error"]` after invoking).

Example (illustrative — the real wiring belongs to `api-routes`):

    final_state = agentic_ai.invoke({
        "run_id": run.id,
        "session_id": session.id,
        "dataset_id": dataset.id,
        "question": question_text,
        "dataframe_loader": lambda ds_id: pd.read_csv(dataset.file_path),
        "context_loader": lambda ds_id, sess_id: {
            "dataset_schema": dataset.schema_json,
            "dataset_anomalies": dataset.anomalies_json,
            "conversation_history": load_recent_messages(sess_id),
        },
        "persist_fn": lambda state: write_run_and_steps(db_session, state),
    })
"""

from langgraph.graph import StateGraph, END

from graph.state import AnalysisState
from graph.nodes import (
    load_context,
    classify_request,
    ask_clarification,
    generate_code,
    execute_code,
    observe_and_decide,
    show_stuck_point,
    finalize,
    persist_run,
    handle_error,
)
from graph.edges import (
    after_load_context,
    after_classify,
    after_generate_code,
    after_observe,
)


def _build_graph() -> StateGraph:
    g = StateGraph(AnalysisState)

    for name, fn in [
        ("load_context", load_context),
        ("classify_request", classify_request),
        ("ask_clarification", ask_clarification),
        ("generate_code", generate_code),
        ("execute_code", execute_code),
        ("observe_and_decide", observe_and_decide),
        ("show_stuck_point", show_stuck_point),
        ("finalize", finalize),
        ("persist_run", persist_run),
        ("handle_error", handle_error),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("load_context")

    g.add_conditional_edges(
        "load_context",
        after_load_context,
        {"classify_request": "classify_request", "handle_error": "handle_error"},
    )

    g.add_conditional_edges(
        "classify_request",
        after_classify,
        {
            "ask_clarification": "ask_clarification",
            "generate_code": "generate_code",
            "handle_error": "handle_error",
        },
    )

    g.add_conditional_edges(
        "generate_code",
        after_generate_code,
        {"execute_code": "execute_code", "handle_error": "handle_error"},
    )

    g.add_edge("execute_code", "observe_and_decide")

    g.add_conditional_edges(
        "observe_and_decide",
        after_observe,
        {
            "finalize": "finalize",
            "generate_code": "generate_code",
            "show_stuck_point": "show_stuck_point",
        },
    )

    g.add_edge("show_stuck_point", "finalize")
    g.add_edge("finalize", "persist_run")
    g.add_edge("ask_clarification", "persist_run")
    g.add_edge("persist_run", END)
    g.add_edge("handle_error", END)

    return g.compile()


agentic_ai = _build_graph()
