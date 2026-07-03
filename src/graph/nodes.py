"""The ask-a-question LangGraph nodes (spec/agent.md).

Dependency injection: `load_context` needs a real DataFrame and (usually)
persisted dataset schema/anomalies/conversation history, but this module has
NO DB dependency of its own — see the injection contract documented in
`graph/agent.py`.

Privacy Boundary: every LLM-facing prompt built in this file is constructed
from `dataset_schema` / `dataset_anomalies` / `execution_result` (already
sanitized by `tools.sandbox.sanitize_result`) / `conversation_history` /
`code_attempts` — never from a raw DataFrame or `execution_full_result`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config.settings import get_settings
from graph.state import AnalysisState
from llm.client import LLMClient, estimate_cost_usd
from observability.events import get_logger
from tools.chart import build_chart_spec, build_key_numbers, build_table_data
from tools.sandbox import run_user_code

try:
    from tools.profiling import detect_anomalies as _detect_anomalies
except ImportError:  # pragma: no cover - only if dataset-ingestion hasn't landed yet
    _detect_anomalies = None

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_MAX_HISTORY_TURNS = 10
_DEFAULT_MAX_ATTEMPTS = 3

log = get_logger("graph")

# In-process DataFrame cache, keyed by dataset_id (spec/agent.md: "loads the
# real CSV into an in-process cache ... first access per dataset; cached
# thereafter"). This is the ONLY place a full DataFrame lives across nodes —
# it is never put into the LangGraph state dict, so it can never leak into a
# checkpoint, a log line, or (by construction) an LLM prompt.
_dataframe_cache: dict[str, pd.DataFrame] = {}


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def _append_step(state: AnalysisState, step_type: str, label: str, *, is_error: bool = False, code_snippet: str | None = None, output_summary: str | None = None) -> tuple[list[dict], int]:
    steps = list(state.get("steps") or [])
    step_count = state.get("step_count", 0) + 1
    steps.append(
        {
            "step_number": step_count,
            "step_type": step_type,
            "label": label,
            "is_error": is_error,
            "code_snippet": code_snippet,
            "output_summary": output_summary,
        }
    )
    return steps, step_count


def _fast_client() -> LLMClient:
    return LLMClient(model=get_settings().llm_model_fast)


def _quality_client() -> LLMClient:
    return LLMClient(model=get_settings().llm_model_quality)


def _accumulate_usage(state: AnalysisState, client: LLMClient) -> dict:
    """Adds `client.last_usage` (the call just made) onto the running
    `token_usage` total carried in state (spec/agent.md: "running total
    across LLM calls this run")."""
    usage = dict(state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0})
    call_usage = client.last_usage
    usage["input_tokens"] = usage.get("input_tokens", 0) + call_usage.get("input_tokens", 0)
    usage["output_tokens"] = usage.get("output_tokens", 0) + call_usage.get("output_tokens", 0)
    return usage


# ---------------------------------------------------------------------------
# load_context
# ---------------------------------------------------------------------------


def load_context(state: AnalysisState) -> AnalysisState:
    try:
        dataset_id = state["dataset_id"]
        session_id = state.get("session_id")

        if dataset_id not in _dataframe_cache:
            loader = state.get("dataframe_loader")
            if loader is None:
                raise RuntimeError(
                    "No DataFrame cached for this dataset and no `dataframe_loader` "
                    "was provided in the initial state."
                )
            _dataframe_cache[dataset_id] = loader(dataset_id)

        dataset_schema = state.get("dataset_schema")
        dataset_anomalies = state.get("dataset_anomalies")
        conversation_history = state.get("conversation_history")

        if dataset_schema is None or dataset_anomalies is None or conversation_history is None:
            loader = state.get("context_loader")
            if loader is not None:
                ctx = loader(dataset_id, session_id) or {}
                dataset_schema = dataset_schema if dataset_schema is not None else ctx.get("dataset_schema", {})
                dataset_anomalies = (
                    dataset_anomalies if dataset_anomalies is not None else ctx.get("dataset_anomalies", [])
                )
                conversation_history = (
                    conversation_history
                    if conversation_history is not None
                    else ctx.get("conversation_history", [])
                )

        dataset_schema = dataset_schema or {}
        dataset_anomalies = dataset_anomalies or []
        conversation_history = (conversation_history or [])[-_MAX_HISTORY_TURNS:]

        steps, step_count = _append_step(state, "load_context", "Loading dataset context")

        return {
            **state,
            "dataset_schema": dataset_schema,
            "dataset_anomalies": dataset_anomalies,
            "conversation_history": conversation_history,
            "max_attempts": state.get("max_attempts", _DEFAULT_MAX_ATTEMPTS),
            "attempt_count": state.get("attempt_count", 0),
            "code_attempts": state.get("code_attempts", []),
            "token_usage": state.get("token_usage", {"input_tokens": 0, "output_tokens": 0}),
            "steps": steps,
            "step_count": step_count,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        log.error("load_context_failed", error=str(exc))
        return {**state, "error": f"load_context failed: {exc}"}


# ---------------------------------------------------------------------------
# classify_request
# ---------------------------------------------------------------------------


def _build_classify_prompt(state: AnalysisState) -> str:
    payload = {
        "question": state.get("question"),
        "dataset_schema": state.get("dataset_schema"),
        "dataset_anomalies": state.get("dataset_anomalies"),
        "conversation_history": state.get("conversation_history"),
    }
    return json.dumps(payload, default=str)


def classify_request(state: AnalysisState) -> AnalysisState:
    try:
        system = _load_prompt("classify_request")
        client = _fast_client()
        result = client.call_json(_build_classify_prompt(state), system=system)

        steps, step_count = _append_step(
            state,
            "classify_request",
            "Understanding the question",
            output_summary=result.get("plan") or result.get("clarification_question"),
        )

        return {
            **state,
            "clarification_needed": bool(result.get("clarification_needed", False)),
            "clarification_question": result.get("clarification_question"),
            "plan": result.get("plan"),
            "assumptions": result.get("assumptions") or [],
            "token_usage": _accumulate_usage(state, client),
            "steps": steps,
            "step_count": step_count,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        log.error("classify_request_failed", error=str(exc))
        return {**state, "error": f"classify_request failed: {exc}"}


# ---------------------------------------------------------------------------
# ask_clarification
# ---------------------------------------------------------------------------


def ask_clarification(state: AnalysisState) -> AnalysisState:
    steps, step_count = _append_step(state, "ask_clarification", "Asking a clarifying question")
    token_usage = state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0}
    estimated_cost_usd = estimate_cost_usd(
        get_settings().llm_model_fast, token_usage.get("input_tokens", 0), token_usage.get("output_tokens", 0)
    )
    return {
        **state,
        "answer_text": state.get("clarification_question"),
        "status": "needs_clarification",
        "estimated_cost_usd": estimated_cost_usd,
        "steps": steps,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# generate_code
# ---------------------------------------------------------------------------


def _build_generate_code_prompt(state: AnalysisState) -> str:
    payload = {
        "question": state.get("question"),
        "plan": state.get("plan"),
        "dataset_schema": state.get("dataset_schema"),
        "dataset_anomalies": state.get("dataset_anomalies"),
        "prior_attempts": state.get("code_attempts", []),
        "instruction": (
            "Try a different approach from any prior attempt shown above."
            if state.get("code_attempts")
            else None
        ),
    }
    return json.dumps(payload, default=str)


def generate_code(state: AnalysisState) -> AnalysisState:
    try:
        system = _load_prompt("generate_code")
        client = _quality_client()
        result = client.call_json(_build_generate_code_prompt(state), system=system)
        code = result.get("code", "")
        if not code or "def analyze" not in code:
            raise ValueError("Model did not return a valid `analyze` function body.")

        attempt_count = state.get("attempt_count", 0) + 1
        steps, step_count = _append_step(
            state,
            "generate_code",
            f"Writing analysis code (attempt {attempt_count})",
            code_snippet=code,
        )

        return {
            **state,
            "generated_code": code,
            "attempt_count": attempt_count,
            "token_usage": _accumulate_usage(state, client),
            "steps": steps,
            "step_count": step_count,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        log.error("generate_code_failed", error=str(exc))
        return {**state, "error": f"generate_code failed: {exc}"}


# ---------------------------------------------------------------------------
# execute_code
# ---------------------------------------------------------------------------


def execute_code(state: AnalysisState) -> AnalysisState:
    df = _dataframe_cache.get(state["dataset_id"])
    outcome = run_user_code(state.get("generated_code", ""), df)

    steps, step_count = _append_step(
        state,
        "execute_code",
        "Running analysis code",
        is_error=bool(outcome["error"]),
        code_snippet=state.get("generated_code"),
        output_summary=outcome["error"] or json.dumps(outcome["result"], default=str)[:500],
    )

    return {
        **state,
        "execution_full_result": outcome["full_result"],
        "execution_result": outcome["result"],
        "execution_error": outcome["error"],
        "steps": steps,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# observe_and_decide
# ---------------------------------------------------------------------------


def _build_observe_prompt(state: AnalysisState) -> str:
    payload = {
        "question": state.get("question"),
        "execution_result": state.get("execution_result"),
        "execution_error": state.get("execution_error"),
        "attempt_count": state.get("attempt_count", 0),
        "max_attempts": state.get("max_attempts", _DEFAULT_MAX_ATTEMPTS),
    }
    return json.dumps(payload, default=str)


def observe_and_decide(state: AnalysisState) -> AnalysisState:
    token_usage = state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0}
    try:
        system = _load_prompt("observe_and_decide")
        client = _fast_client()
        result = client.call_json(_build_observe_prompt(state), system=system)
        sufficient = bool(result.get("sufficient", False))
        reason = result.get("reason", "")
        token_usage = _accumulate_usage(state, client)
    except Exception as exc:  # noqa: BLE001
        log.error("observe_and_decide_failed", error=str(exc))
        sufficient = False
        reason = f"observation step failed: {exc}"

    attempt_count = state.get("attempt_count", 0)
    max_attempts = state.get("max_attempts", _DEFAULT_MAX_ATTEMPTS)
    attempts_exhausted = attempt_count >= max_attempts

    code_attempts = list(state.get("code_attempts") or [])
    code_attempts.append(
        {
            "attempt": attempt_count,
            "code": state.get("generated_code"),
            "error_or_summary": state.get("execution_error") or reason,
        }
    )

    stuck = (not sufficient) and attempts_exhausted

    steps, step_count = _append_step(
        state,
        "observe_and_decide",
        "Deciding whether the result answers the question",
        output_summary=reason,
    )

    return {
        **state,
        "code_attempts": code_attempts,
        "stuck": stuck,
        "token_usage": token_usage,
        "steps": steps,
        "step_count": step_count,
        "_sufficient": sufficient,
    }


# ---------------------------------------------------------------------------
# show_stuck_point
# ---------------------------------------------------------------------------


def show_stuck_point(state: AnalysisState) -> AnalysisState:
    token_usage = state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0}
    try:
        system = _load_prompt("show_stuck_point")
        payload = json.dumps({"question": state.get("question"), "code_attempts": state.get("code_attempts", [])}, default=str)
        client = _fast_client()
        explanation = client.call_model(payload, system=system)
        token_usage = _accumulate_usage(state, client)
    except Exception as exc:  # noqa: BLE001
        log.error("show_stuck_point_failed", error=str(exc))
        explanation = (
            f"I tried {state.get('attempt_count', 0)} approach(es) but couldn't produce a "
            "reliable answer to this question."
        )

    steps, step_count = _append_step(state, "show_stuck_point", "Explaining what went wrong")

    return {
        **state,
        "stuck_explanation": explanation,
        "status": "failed",
        "token_usage": token_usage,
        "steps": steps,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


def _build_finalize_prompt(state: AnalysisState) -> str:
    payload = {
        "question": state.get("question"),
        "execution_result": state.get("execution_result"),
        "assumptions": state.get("assumptions", []),
        "dataset_anomalies": state.get("dataset_anomalies", []),
    }
    return json.dumps(payload, default=str)


def finalize(state: AnalysisState) -> AnalysisState:
    full_result = state.get("execution_full_result")
    chart_spec = build_chart_spec(full_result)
    table_data = build_table_data(full_result)
    key_numbers = build_key_numbers(full_result)
    token_usage = state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0}

    if state.get("stuck"):
        answer_text = state.get("stuck_explanation") or "I wasn't able to answer this question."
        status = "failed"
    else:
        try:
            system = _load_prompt("finalize")
            client = _quality_client()
            answer_text = client.call_model(_build_finalize_prompt(state), system=system)
            token_usage = _accumulate_usage(state, client)
            status = "completed"
        except Exception as exc:  # noqa: BLE001
            log.error("finalize_failed", error=str(exc))
            answer_text = "The analysis completed, but I couldn't compose a summary."
            status = "completed"

    anomalies = list(state.get("dataset_anomalies") or [])
    if _detect_anomalies is not None and isinstance(full_result, dict):
        for value in full_result.values():
            if isinstance(value, pd.DataFrame) and len(value) > 0:
                try:
                    anomalies.extend(a.to_dict() for a in _detect_anomalies(value))
                except Exception:  # noqa: BLE001 - best-effort only
                    pass

    steps, step_count = _append_step(state, "finalize", "Composing the answer")
    model_used = get_settings().llm_model_quality
    estimated_cost_usd = estimate_cost_usd(
        model_used, token_usage.get("input_tokens", 0), token_usage.get("output_tokens", 0)
    )

    return {
        **state,
        "answer_text": answer_text,
        "key_numbers": key_numbers,
        "chart_spec": chart_spec,
        "table_data": table_data,
        "dataset_anomalies": anomalies,
        "status": status,
        "token_usage": token_usage,
        "estimated_cost_usd": estimated_cost_usd,
        "steps": steps,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# persist_run
# ---------------------------------------------------------------------------


def persist_run(state: AnalysisState) -> AnalysisState:
    """Terminal node. Delegates the actual DB write to `state["persist_fn"]`
    (see the injection contract documented atop `graph/agent.py`). If no
    `persist_fn` is supplied, this is a local no-op — useful for testing the
    graph without a database.
    """
    persist_fn = state.get("persist_fn")
    if persist_fn is None:
        return state
    try:
        run_id = persist_fn(state)
        return {**state, "run_id": run_id or state.get("run_id")}
    except Exception as exc:  # noqa: BLE001
        log.error("persist_run_failed", error=str(exc), run_id=state.get("run_id"))
        # Per spec/agent.md: persist_run failures are fatal — the audit
        # trail is non-negotiable. The graph's fixed topology routes
        # persist_run straight to END regardless, so we surface the
        # failure via `status`/`error` for the caller to detect.
        return {**state, "status": "failed", "error": f"persist_run failed: {exc}"}


# ---------------------------------------------------------------------------
# handle_error
# ---------------------------------------------------------------------------


def handle_error(state: AnalysisState) -> AnalysisState:
    log.error("run_failed", run_id=state.get("run_id"), error=state.get("error"))
    return {**state, "status": "failed"}
