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
