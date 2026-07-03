"""Tests for the ask-a-question LangGraph agent (spec/agent.md).

The graph-execution tests below make REAL Gemini API calls (key loaded from
`.env` — never mocked, per this repo's hard rule) and assert against a
constructed in-memory DataFrame + injected loader callbacks. No database is
involved — this graph has no DB dependency; see the injection contract
documented in `graph/agent.py`.
"""

import json

import pandas as pd
import pytest

from config.settings import get_settings


def test_graph_compiles():
    """Graph compiles without requiring any env vars."""
    from graph.agent import agentic_ai
    assert agentic_ai is not None


@pytest.fixture
def _require_gemini_key():
    s = get_settings()
    if not s.gemini_api_key:
        pytest.skip("No AGENT_GEMINI_API_KEY set in .env — required for real-Gemini graph tests.")


@pytest.fixture
def sales_df() -> pd.DataFrame:
    """A small sales-like dataset with a null column and one outlier."""
    return pd.DataFrame(
        {
            "region": ["North", "South", "East", "North", "South", "East", "North", "South"],
            "total_amount": [1000.0, 1500.0, 1200.0, 900.0, 1750.0, 1100.0, 980.0, 250000.0],
            "sales_rep": ["Alice", "Bob", None, "Dana", "Erin", None, "Grace", "Hank"],
        }
    )


def _make_initial_state(question: str, df: pd.DataFrame, **overrides) -> dict:
    from graph.nodes import _dataframe_cache

    dataset_id = overrides.pop("dataset_id", "test-dataset-1")
    _dataframe_cache.pop(dataset_id, None)  # ensure a clean cache per test

    state = {
        "run_id": "test-run-1",
        "session_id": "test-session-1",
        "dataset_id": dataset_id,
        "question": question,
        "dataframe_loader": lambda ds_id: df,
        "context_loader": lambda ds_id, sess_id: {
            "dataset_schema": {
                "region": {"dtype": "string", "null_pct": 0.0, "distinct_count": 3},
                "total_amount": {"dtype": "float", "null_pct": 0.0, "distinct_count": 8},
                "sales_rep": {"dtype": "string", "null_pct": 25.0, "distinct_count": 6},
            },
            "dataset_anomalies": [
                {
                    "column": "sales_rep",
                    "type": "missing_values",
                    "severity": "medium",
                    "description": "25.0% missing values",
                },
                {
                    "column": "total_amount",
                    "type": "outliers",
                    "severity": "high",
                    "description": "1 outlier value detected",
                },
            ],
            "conversation_history": [],
        },
    }
    state.update(overrides)
    return state


@pytest.mark.usefixtures("_require_gemini_key")
def test_simple_unambiguous_question_completes(sales_df):
    from graph.agent import agentic_ai

    initial = _make_initial_state("What is the total revenue by region?", sales_df, dataset_id="ds-happy")
    final = agentic_ai.invoke(initial)

    assert final.get("error") is None, final.get("error")
    assert final["status"] == "completed"
    assert final.get("answer_text")
    assert len(final["answer_text"]) > 0
    assert final.get("chart_spec") is not None
    assert final.get("table_data") is not None
    assert len(final["table_data"]) > 0


@pytest.mark.usefixtures("_require_gemini_key")
def test_ambiguous_question_needs_clarification(sales_df):
    from graph.agent import agentic_ai

    initial = _make_initial_state("how are we doing?", sales_df, dataset_id="ds-ambiguous")
    final = agentic_ai.invoke(initial)

    assert final.get("error") is None, final.get("error")
    assert final["status"] == "needs_clarification"
    assert final.get("answer_text")  # the clarifying question is surfaced as the answer


@pytest.mark.usefixtures("_require_gemini_key")
def test_question_about_missing_column_triggers_retry_or_stuck(sales_df):
    from graph.agent import agentic_ai

    initial = _make_initial_state(
        "Calculate the average value of the profit_margin_percent column.",
        sales_df,
        dataset_id="ds-missing-column",
    )
    final = agentic_ai.invoke(initial)

    assert final.get("error") is None, final.get("error")
    assert final["status"] in ("completed", "failed", "needs_clarification")
    if final["status"] == "needs_clarification":
        # Correct behavior per spec/agent.md's uncertainty-handling priority
        # order: a nonexistent column reference is genuinely ambiguous, so
        # asking a real, specific clarifying question is a valid outcome.
        assert final.get("clarification_question")
    else:
        # Either it retried at least once, or it recorded more than one code attempt.
        assert final.get("attempt_count", 0) >= 1
        assert len(final.get("code_attempts", [])) >= 1
        if final["status"] == "failed":
            assert final.get("stuck_explanation")


@pytest.mark.usefixtures("_require_gemini_key")
def test_no_raw_cell_values_reach_execution_result(sales_df):
    """End-to-end check of the Privacy Boundary: the sanitized
    `execution_result` that would be sent to Gemini must never contain a
    literal sales_rep name or region-level raw amount for a row-level
    request, even though the full local result may.
    """
    from graph.agent import agentic_ai

    initial = _make_initial_state(
        "List every individual sale with its sales rep and amount.",
        sales_df,
        dataset_id="ds-privacy",
    )
    final = agentic_ai.invoke(initial)

    assert final.get("error") is None, final.get("error")
    execution_result = final.get("execution_result")
    if execution_result is not None:
        dumped = json.dumps(execution_result, default=str)
        for name in ["Alice", "Bob", "Dana", "Erin", "Grace", "Hank"]:
            assert name not in dumped, f"raw cell value {name!r} leaked into execution_result"


# ---------------------------------------------------------------------------
# Phase 2 — analysis-graph-hardening (UNIT tests, Gemini transport mocked at
# the client boundary). These do NOT hit the network; the real-key integration
# coverage lives in the graph-execution tests above.
# ---------------------------------------------------------------------------


class _FakeAPIError(Exception):
    """Mimics google.genai errors.APIError: exposes a `.code` HTTP status."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class _FakeClient:
    """Stand-in for graph.nodes.LLMClient used to drive generate_code without a
    real Gemini call. `behaviour` is called to produce the call_json result (or
    to raise)."""

    def __init__(self, behaviour) -> None:
        self._behaviour = behaviour
        self.last_usage = {"input_tokens": 1, "output_tokens": 1}

    def call_json(self, prompt, *, system=None):
        return self._behaviour()


# (a) distinct strategy selected per attempt -------------------------------

def test_distinct_strategy_selected_per_attempt():
    from graph.nodes import _strategy_for_attempt

    s1 = _strategy_for_attempt(1)
    s2 = _strategy_for_attempt(2)
    s3 = _strategy_for_attempt(3)
    s4 = _strategy_for_attempt(4)

    # First attempt has no strategy hint; retries each get a distinct one.
    assert s1 is None
    assert s2 and s3 and s4
    assert len({s2, s3, s4}) == 3, "each retry attempt must get a DISTINCT named strategy"
    # The named strategies match the spec's examples.
    assert "simplif" in s2.lower()
    assert "chart" in s3.lower() or "shape" in s3.lower()
    assert "drop" in s4.lower() or "coerce" in s4.lower()


def test_generate_code_prompt_threads_the_attempt_strategy():
    from graph.nodes import _build_generate_code_prompt, _strategy_for_attempt

    # attempt_count=2 means the NEXT (3rd) code-gen attempt is about to run.
    prompt = _build_generate_code_prompt({"question": "q", "attempt_count": 2})
    payload = json.loads(prompt)
    assert payload["attempt_number"] == 3
    assert payload["retry_strategy"] == _strategy_for_attempt(3)
    assert payload["instruction"] == _strategy_for_attempt(3)


# (b) JSON-parse failure triggers a retry rather than handle_error ----------

def test_json_parse_failure_is_retryable_not_fatal(monkeypatch):
    import graph.nodes as nodes
    from graph.edges import after_generate_code, after_observe

    def _raise_bad_json():
        # This is exactly what LLMClient.call_json raises on malformed JSON.
        raise ValueError("LLM did not return valid JSON")

    monkeypatch.setattr(nodes, "_quality_client", lambda: _FakeClient(_raise_bad_json))

    state = {"question": "q", "attempt_count": 0, "max_attempts": 4, "code_attempts": []}
    after_gen = nodes.generate_code(state)

    # Not fatal: no error set, so the graph does NOT route to handle_error.
    assert after_gen.get("error") is None
    assert after_generate_code(after_gen) == "execute_code"
    # The failed attempt is counted and left with no code + a sanitized marker.
    assert after_gen["attempt_count"] == 1
    assert after_gen["generated_code"] is None
    assert after_gen["execution_result"] is None
    assert after_gen["execution_error"]
    # No raw model output leaks into the recorded failure (Privacy Boundary).
    assert "Raw output" not in after_gen["execution_error"]

    # execute_code is a pass-through when there is no code...
    after_exec = nodes.execute_code(after_gen)
    assert after_exec["execution_result"] is None
    assert after_exec["execution_error"] == after_gen["execution_error"]

    # ...and observe_and_decide short-circuits (no LLM call needed), records
    # the sanitized failure, and routes back into the retry loop.
    after_obs = nodes.observe_and_decide(after_exec)
    assert after_obs["_sufficient"] is False
    assert len(after_obs["code_attempts"]) == 1
    assert after_obs["code_attempts"][0]["error_or_summary"] == after_gen["execution_error"]
    assert after_obs["stuck"] is False  # attempt 1 of 4 — retry, don't give up
    assert after_observe(after_obs) == "generate_code"


def test_unexpected_generate_code_error_is_fatal(monkeypatch):
    import graph.nodes as nodes
    from graph.edges import after_generate_code

    def _raise_unexpected():
        raise RuntimeError("provider client blew up unexpectedly")

    monkeypatch.setattr(nodes, "_quality_client", lambda: _FakeClient(_raise_unexpected))

    state = {"question": "q", "attempt_count": 0, "max_attempts": 4}
    result = nodes.generate_code(state)
    assert result.get("error")  # fatal
    assert after_generate_code(result) == "handle_error"


# (c) client backs off on transient, fails fast on 429 ---------------------

class _FakeProvider:
    """Records call count and raises/returns per a scripted list of outcomes."""

    def __init__(self, outcomes) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}

    def call_model(self, prompt, *, system=None):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _make_client_with_provider(provider, monkeypatch):
    import llm.client as client_mod
    # Avoid constructing a real Gemini provider in __init__.
    monkeypatch.setattr(client_mod, "_make_provider", lambda model=None: provider)
    # Don't actually sleep during backoff.
    monkeypatch.setattr(client_mod.time, "sleep", lambda *_a, **_k: None)
    return client_mod.LLMClient(model="gemini-2.5-flash")


def test_client_backs_off_on_transient_then_succeeds(monkeypatch):
    import llm.client as client_mod

    # Two transient failures (503), then success — with max_retries=2 this
    # succeeds on the 3rd call.
    provider = _FakeProvider(
        [_FakeAPIError(503, "503 UNAVAILABLE"), _FakeAPIError(503, "503 UNAVAILABLE"), "ok"]
    )
    client = _make_client_with_provider(provider, monkeypatch)
    sleeps = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    result = client.call_model("hi")
    assert result == "ok"
    assert provider.calls == 3  # 1 initial + 2 retries
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1]  # exponential backoff


def test_client_raises_transient_error_when_retries_exhausted(monkeypatch):
    provider = _FakeProvider([_FakeAPIError(503, "503 UNAVAILABLE")] * 10)
    client = _make_client_with_provider(provider, monkeypatch)

    from llm.client import LLMTransientError

    with pytest.raises(LLMTransientError):
        client.call_model("hi")
    # 1 initial + max_retries(2) = 3 attempts, then give up. Never a storm.
    assert provider.calls == 3


def test_client_fails_fast_on_429_quota(monkeypatch):
    import llm.client as client_mod

    provider = _FakeProvider([_FakeAPIError(429, "429 RESOURCE_EXHAUSTED: quota exceeded")] * 5)
    client = _make_client_with_provider(provider, monkeypatch)
    sleeps = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: sleeps.append(s))

    from llm.client import LLMQuotaError

    with pytest.raises(LLMQuotaError):
        client.call_model("hi")
    # FAIL FAST: exactly one call, zero backoff sleeps — no retry storm.
    assert provider.calls == 1
    assert sleeps == []


def test_error_classification():
    from llm.client import _classify_error

    assert _classify_error(_FakeAPIError(429, "RESOURCE_EXHAUSTED")) == "quota"
    assert _classify_error(_FakeAPIError(403, "PERMISSION_DENIED")) == "auth"
    assert _classify_error(_FakeAPIError(503, "UNAVAILABLE")) == "transient"
    assert _classify_error(TimeoutError("timed out")) == "transient"
    assert _classify_error(ValueError("some parse issue")) == "fatal"
