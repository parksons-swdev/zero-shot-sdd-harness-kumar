"""Tests for the Privacy Boundary classifier and code sandbox.

These are the single most safety-critical tests in the project: they
directly assert that no raw cell value from the DataFrame ever survives
`sanitize_result`, independent of any LLM call.
"""

import time

import pandas as pd
import pytest

from tools.sandbox import SandboxError, run_user_code, sanitize_result


def _sales_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer": [f"Customer_{i}" for i in range(50)],
            "region": ["North", "South"] * 25,
            "revenue": [1000 + i for i in range(50)],
        }
    )


# ---------------------------------------------------------------------------
# sanitize_result — the Privacy Boundary classifier
# ---------------------------------------------------------------------------


def test_sanitize_passes_through_small_aggregate():
    full_result = {"total_by_region": {"North": 120000, "South": 98500}}
    sanitized = sanitize_result(full_result)
    assert sanitized == full_result


def test_sanitize_strips_row_level_list_of_records():
    df = _sales_df()
    # Simulates `analyze` returning the top customers — row-level data.
    full_result = {"top_customers": df.to_dict(orient="records")}
    sanitized = sanitize_result(full_result)

    dumped = str(sanitized)
    for name in df["customer"]:
        assert name not in dumped
    assert sanitized["top_customers"]["_type"] == "list"
    assert sanitized["top_customers"]["length"] == 50
    assert set(sanitized["top_customers"]["columns"]) == {"customer", "region", "revenue"}


def test_sanitize_strips_large_dataframe_value():
    df = _sales_df()
    full_result = {"raw_rows": df}
    sanitized = sanitize_result(full_result)

    dumped = str(sanitized)
    for name in df["customer"]:
        assert name not in dumped
    assert sanitized["raw_rows"]["_type"] == "dataframe"
    assert sanitized["raw_rows"]["shape"] == [50, 3]


def test_sanitize_never_passes_through_small_dataframe():
    """A DataFrame is a multi-field record structure by construction — it
    must never pass through literal values, even when small, because row
    count alone cannot distinguish a safe aggregate from a row-level record
    dump. The safe way to express a small aggregate is a flat dict
    (`series.to_dict()`), not a DataFrame."""
    small = pd.DataFrame({"region": ["North", "South"], "total": [120000, 98500]})
    sanitized = sanitize_result({"by_region": small})
    assert sanitized["by_region"]["_type"] == "dataframe"
    assert sanitized["by_region"]["shape"] == [2, 2]
    assert set(sanitized["by_region"]["columns"]) == {"region", "total"}


def test_sanitize_passes_through_small_scalar_list():
    full_result = {"totals": [120000, 98500, 45000]}
    sanitized = sanitize_result(full_result)
    assert sanitized == full_result


def test_sanitize_passes_through_small_dict_of_scalars():
    """The natural shape of `pandas.Series.to_dict()` from a
    `groupby().sum()` — a flat mapping of category to scalar metric — is a
    legitimate, safe aggregate and must keep passing through with real
    values."""
    full_result = {"total_by_region": {"North": 5000.0, "South": 3200.0}}
    sanitized = sanitize_result(full_result)
    assert sanitized == full_result


def test_sanitize_always_strips_small_list_of_dict_records():
    """A list of dict items (multi-field records) must NEVER pass through
    with literal values, regardless of length — this is the row-level-dump
    collision the Privacy Boundary must close. Confirmed at a size well
    under MAX_AGGREGATE_ROWS."""
    full_result = {
        "sales": [
            {"sales_rep": "Alice", "amount": 1000.0},
            {"sales_rep": "Bob", "amount": 1500.0},
            {"sales_rep": "Dana", "amount": 900.0},
        ]
    }
    sanitized = sanitize_result(full_result)
    dumped = str(sanitized)
    for name in ["Alice", "Bob", "Dana"]:
        assert name not in dumped
    assert sanitized["sales"]["_type"] == "list"
    assert sanitized["sales"]["length"] == 3
    assert set(sanitized["sales"]["columns"]) == {"sales_rep", "amount"}


def test_sanitize_strips_large_list_of_dict_records():
    """Already worked before this fix; keep it working: a list of dict
    records larger than MAX_AGGREGATE_ROWS is reduced to metadata."""
    full_result = {
        "sales": [{"sales_rep": f"Rep_{i}", "amount": float(i)} for i in range(25)]
    }
    sanitized = sanitize_result(full_result)
    assert sanitized["sales"]["_type"] == "list"
    assert sanitized["sales"]["length"] == 25
    for i in range(25):
        assert f"Rep_{i}" not in str(sanitized)


def test_sanitize_handles_none_and_non_dict():
    assert sanitize_result(None) is None
    assert sanitize_result([1, 2, 3]) == {"_type": "list"}


def test_sanitize_scalar_passthrough():
    sanitized = sanitize_result({"total_revenue": 1234567.89, "row_count": 50})
    assert sanitized == {"total_revenue": 1234567.89, "row_count": 50}


# ---------------------------------------------------------------------------
# run_user_code — the execution sandbox
# ---------------------------------------------------------------------------


def test_run_user_code_happy_path_aggregate():
    df = _sales_df()
    code = (
        "def analyze(df):\n"
        "    grouped = df.groupby('region')['revenue'].sum()\n"
        "    return {'total_by_region': grouped.to_dict()}\n"
    )
    outcome = run_user_code(code, df)
    assert outcome["error"] is None
    assert outcome["full_result"]["total_by_region"]
    assert outcome["result"] == outcome["full_result"]  # small aggregate passes through


def test_run_user_code_rejects_forbidden_import():
    df = _sales_df()
    code = "import os\ndef analyze(df):\n    return {'x': os.getcwd()}\n"
    outcome = run_user_code(code, df)
    assert outcome["error"] is not None
    assert outcome["full_result"] is None
    assert outcome["result"] is None


def test_run_user_code_rejects_missing_analyze_function():
    df = _sales_df()
    code = "x = 1\n"
    outcome = run_user_code(code, df)
    assert outcome["error"] is not None


def test_run_user_code_captures_runtime_exception_without_crashing():
    df = _sales_df()
    code = "def analyze(df):\n    return df['does_not_exist'].sum()\n"
    outcome = run_user_code(code, df)
    assert outcome["error"] is not None
    assert outcome["full_result"] is None
    # The sanitized error message must not contain any real column's literal values.
    for value in df["customer"]:
        assert value not in outcome["error"]


def test_run_user_code_no_data_loaded():
    code = "def analyze(df):\n    return {}\n"
    outcome = run_user_code(code, None)
    assert outcome["error"] is not None


def test_run_user_code_processes_the_full_frame_not_a_sample():
    """The Phase 2 correctness invariant: the sandbox runs `analyze` over the
    ENTIRE in-memory DataFrame. An aggregate over the full frame must differ
    from the same aggregate over a 1,000-row sample -- proving no sampling is
    silently applied inside the sandbox."""
    import numpy as np

    n = 300_000
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"region": rng.choice(["N", "S"], size=n), "amount": rng.uniform(0, 100, n)})

    code = (
        "def analyze(df):\n"
        "    return {'total': float(df['amount'].sum())}\n"
    )
    start = time.monotonic()
    outcome = run_user_code(df=df, code=code)
    elapsed = time.monotonic() - start

    assert outcome["error"] is None
    full_total = outcome["full_result"]["total"]
    sample_total = float(df.head(1000)["amount"].sum())

    assert full_total != sample_total
    assert abs(full_total - float(df["amount"].sum())) < 1e-3
    # No pathological wrapping overhead on a large frame.
    assert elapsed < 10.0


def test_default_timeout_protects_the_30s_budget():
    from tools.sandbox import DEFAULT_TIMEOUT_SECONDS

    # A wall-clock ceiling below 30s so the sandbox can never blow the
    # end-to-end latency budget.
    assert DEFAULT_TIMEOUT_SECONDS <= 25.0
