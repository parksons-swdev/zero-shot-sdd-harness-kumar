"""Unit tests for `src/tools/profiling.py` -- schema profiling and
deterministic anomaly detection.

Covers: a clean CSV, a CSV with nulls, a CSV with a numeric outlier, a CSV
with a mixed-format date column, and the canonical fixture (all combined).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from domain.dataset import Anomaly, ColumnProfile, DatasetProfile
from tools.ingestion import parse_csv
from tools.profiling import (
    ANOMALY_INCONSISTENT_FORMAT,
    ANOMALY_MISSING_VALUES,
    ANOMALY_OUTLIERS,
    build_dataset_profile,
    detect_anomalies,
    profile_dataframe,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_sales.csv"


def _load_fixture() -> pd.DataFrame:
    result = parse_csv(str(FIXTURE_PATH))
    return result.df


def test_profile_dataframe_computes_accurate_schema_for_a_clean_csv():
    df = pd.DataFrame({"id": [1, 2, 3, 4], "name": ["a", "b", "c", "d"]})

    profiles = profile_dataframe(df)

    by_name = {p.name: p for p in profiles}
    assert by_name["id"].dtype == "integer"
    assert by_name["id"].null_count == 0
    assert by_name["id"].null_pct == 0.0
    assert by_name["id"].distinct_count == 4
    assert by_name["id"].min == 1.0
    assert by_name["id"].max == 4.0
    assert by_name["name"].dtype == "string"
    assert by_name["name"].min is None


def test_profile_dataframe_reports_null_percentage_accurately():
    df = pd.DataFrame({"value": [1.0, None, None, 4.0]})

    profiles = profile_dataframe(df)

    value_profile = profiles[0]
    assert value_profile.null_count == 2
    assert value_profile.null_pct == 50.0


def test_detect_anomalies_flags_high_missing_value_columns():
    df = pd.DataFrame({"value": [1, None, None, None, None, 6]})

    anomalies = detect_anomalies(df)

    missing = [a for a in anomalies if a.type == ANOMALY_MISSING_VALUES]
    assert len(missing) == 1
    assert missing[0].column == "value"
    assert missing[0].severity in ("low", "medium", "high")


def test_detect_anomalies_flags_an_obvious_numeric_outlier():
    df = pd.DataFrame({"revenue": [100, 110, 105, 95, 102, 98, 108, 99999]})

    anomalies = detect_anomalies(df)

    outliers = [a for a in anomalies if a.type == ANOMALY_OUTLIERS]
    assert len(outliers) == 1
    assert outliers[0].column == "revenue"


def test_detect_anomalies_flags_mixed_format_dates():
    df = pd.DataFrame(
        {
            "signup_date": [
                "2024-01-01",
                "2024-02-15",
                "01/03/2024",
                "02/20/2024",
                "15-Mar-2024",
            ]
        }
    )

    anomalies = detect_anomalies(df)

    formats = [a for a in anomalies if a.type == ANOMALY_INCONSISTENT_FORMAT]
    assert len(formats) == 1
    assert formats[0].column == "signup_date"
    assert "format" in formats[0].description.lower()


def test_detect_anomalies_does_not_flag_a_consistently_formatted_date_column():
    df = pd.DataFrame(
        {"signup_date": ["2024-01-01", "2024-02-15", "2024-03-20", "2024-04-05"]}
    )

    anomalies = detect_anomalies(df)

    formats = [a for a in anomalies if a.type == ANOMALY_INCONSISTENT_FORMAT]
    assert formats == []


def test_detect_anomalies_does_not_flag_a_clean_dataframe_with_no_issues():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": ["x", "y", "z", "w", "v"]})

    anomalies = detect_anomalies(df)

    assert anomalies == []


def test_fixture_csv_produces_anomalies_for_nulls_outlier_and_mixed_dates():
    df = _load_fixture()

    anomalies = detect_anomalies(df)
    types_found = {a.type for a in anomalies}

    assert ANOMALY_MISSING_VALUES in types_found
    assert ANOMALY_OUTLIERS in types_found
    assert ANOMALY_INCONSISTENT_FORMAT in types_found

    date_anomaly = next(a for a in anomalies if a.type == ANOMALY_INCONSISTENT_FORMAT)
    assert date_anomaly.column == "date"

    outlier_anomaly = next(a for a in anomalies if a.type == ANOMALY_OUTLIERS)
    assert outlier_anomaly.column == "revenue"


def test_build_dataset_profile_returns_a_well_formed_profile_for_the_fixture():
    from tools.ingestion import parse_csv as _parse

    parsed = _parse(str(FIXTURE_PATH))

    profile = build_dataset_profile(parsed)

    assert isinstance(profile, DatasetProfile)
    assert profile.row_count == 400
    assert profile.column_count == 5
    assert all(isinstance(c, ColumnProfile) for c in profile.schema)
    assert all(isinstance(a, Anomaly) for a in profile.anomalies)
    schema_names = {c.name for c in profile.schema}
    assert schema_names == {"date", "region", "product", "revenue", "quantity"}

    as_dict = profile.to_dict()
    assert as_dict["row_count"] == 400
    assert as_dict["column_count"] == 5
    assert isinstance(as_dict["schema"], list)
    assert isinstance(as_dict["anomalies"], list)


def test_build_dataset_profile_is_fast_enough_for_a_large_dataframe():
    import time

    import numpy as np

    rng = np.random.default_rng(0)
    n = 200_000
    df = pd.DataFrame(
        {
            "id": np.arange(n),
            "amount": rng.uniform(0, 1000, size=n),
            "category": rng.choice(["a", "b", "c", "d"], size=n),
        }
    )
    from tools.ingestion import ParsedCsv

    parsed = ParsedCsv(df=df, row_count=n, column_count=3, warnings=None)

    start = time.monotonic()
    profile = build_dataset_profile(parsed)
    elapsed = time.monotonic() - start

    assert profile.row_count == n
    assert elapsed < 10.0
