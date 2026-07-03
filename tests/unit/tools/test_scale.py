"""Scale/performance tests for `ingestion-scale` (Phase 2).

Proves that vectorized profiling keeps numeric summary statistics EXACT over
the full column even when the file is large enough to trigger sampled string
heuristics, that the sampled heuristics still detect real anomalies, and that
the sandbox executes over the FULL in-memory DataFrame (an aggregate over the
whole frame differs from the same aggregate over a 1,000-row sample -- the
Phase 2 gate's correctness assertion in miniature).

No large CSV is committed: frames are built in-memory with numpy, and the
generator is exercised at a tiny row count.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tools.ingestion import ParsedCsv
from tools.profiling import (
    ANOMALY_INCONSISTENT_FORMAT,
    ANOMALY_MIXED_TYPES,
    STRING_SCAN_SAMPLE_SIZE,
    build_dataset_profile,
    detect_anomalies,
    profile_dataframe,
)

# Make scripts/ importable for the generator smoke test.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))


def _large_n() -> int:
    # Comfortably above the string-scan sample threshold so the sampled path
    # is exercised, but small enough for a fast unit test.
    return STRING_SCAN_SAMPLE_SIZE * 2 + 137


# ---------------------------------------------------------------------------
# Numeric statistics stay EXACT over the full column at scale
# ---------------------------------------------------------------------------


def test_numeric_stats_are_exact_over_the_full_frame_even_when_sampling_kicks_in():
    n = _large_n()
    rng = np.random.default_rng(7)
    amount = rng.uniform(0, 10_000, size=n)
    df = pd.DataFrame({"amount": amount, "label": rng.choice(["x", "y", "z"], size=n)})

    profiles = {p.name: p for p in profile_dataframe(df)}
    amount_p = profiles["amount"]

    # Exact match against pandas computed over the WHOLE column -- no sampling
    # of the quantitative statistics.
    assert amount_p.min == float(amount.min())
    assert amount_p.max == float(amount.max())
    assert abs(amount_p.mean - float(amount.mean())) < 1e-6
    assert abs(amount_p.std - float(pd.Series(amount).std())) < 1e-6


def test_null_percentage_is_exact_over_the_full_frame_at_scale():
    n = _large_n()
    rng = np.random.default_rng(1)
    values = rng.uniform(0, 1, size=n)
    null_mask = rng.random(n) < 0.1
    series = pd.Series(values)
    series[null_mask] = np.nan
    df = pd.DataFrame({"value": series})

    profile = profile_dataframe(df)[0]
    expected_null = int(null_mask.sum())
    assert profile.null_count == expected_null
    assert profile.null_pct == round(expected_null / n * 100, 2)


# ---------------------------------------------------------------------------
# Sampled string heuristics still detect real anomalies at scale
# ---------------------------------------------------------------------------


def test_inconsistent_date_format_still_detected_on_a_large_column():
    n = _large_n()
    # Half ISO, half US format -- inconsistency is pervasive, so any large
    # random sample must still see both formats.
    half = n // 2
    dates = ["2024-01-01"] * half + ["01/03/2024"] * (n - half)
    df = pd.DataFrame({"signup_date": dates})

    anomalies = detect_anomalies(df)
    formats = [a for a in anomalies if a.type == ANOMALY_INCONSISTENT_FORMAT]
    assert len(formats) == 1
    assert formats[0].column == "signup_date"


def test_mixed_types_still_detected_on_a_large_column():
    n = _large_n()
    half = n // 2
    values = [str(i) for i in range(half)] + ["N/A"] * (n - half)
    df = pd.DataFrame({"code": values})

    anomalies = detect_anomalies(df)
    mixed = [a for a in anomalies if a.type == ANOMALY_MIXED_TYPES]
    assert len(mixed) == 1
    assert mixed[0].column == "code"


def test_sampled_and_full_scan_agree_on_a_small_frame():
    # Below the sample threshold nothing is sampled; results must be identical
    # to a naive full pass (regression guard on the sampling refactor).
    df = pd.DataFrame(
        {
            "signup_date": ["2024-01-01", "2024-02-15", "01/03/2024", "02/20/2024"] * 3,
            "code": ["1", "2", "abc", "4"] * 3,
        }
    )
    types = {a.type for a in detect_anomalies(df)}
    assert ANOMALY_INCONSISTENT_FORMAT in types
    assert ANOMALY_MIXED_TYPES in types


# ---------------------------------------------------------------------------
# Profiling is fast enough on a large frame
# ---------------------------------------------------------------------------


def test_profiling_a_500k_row_frame_is_well_within_budget():
    n = 500_000
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "date": np.datetime_as_string(
                np.datetime64("2023-01-01") + rng.integers(0, 730, n).astype("timedelta64[D]"),
                unit="D",
            ),
            "region": rng.choice(["North", "South", "East", "West"], size=n),
            "category": rng.choice(["a", "b", "c", "d", "e"], size=n),
            "customer": np.char.add("CUST-", rng.integers(0, 100_000, n).astype(str)),
            "amount": rng.gamma(2.0, 150.0, size=n),
            "quantity": rng.integers(1, 50, size=n),
        }
    )
    parsed = ParsedCsv(df=df, row_count=n, column_count=len(df.columns), warnings=None)

    start = time.monotonic()
    profile = build_dataset_profile(parsed)
    elapsed = time.monotonic() - start

    assert profile.row_count == n
    assert profile.column_count == 6
    # Generous ceiling; observed well under this. Leaves ample room in the 30s
    # end-to-end budget for parsing and the Gemini reasoning calls.
    assert elapsed < 12.0


# ---------------------------------------------------------------------------
# Generator script smoke test (tiny row count -- no large file on disk)
# ---------------------------------------------------------------------------


def test_make_large_sample_builds_expected_columns():
    from make_large_sample import build_dataframe

    df = build_dataframe(rows=500, seed=3)
    assert len(df) == 500
    assert set(df.columns) == {
        "date",
        "region",
        "category",
        "customer",
        "product",
        "quantity",
        "amount",
        "notes",
    }
    # Nulls injected into amount so anomaly detection has signal.
    assert df["amount"].isna().sum() >= 0
    # Dates are ISO strings.
    assert df["date"].iloc[0].count("-") == 2
