"""Deterministic, non-LLM schema profiling and anomaly detection.

Given a successfully-parsed DataFrame, computes a per-column schema
profile and a list of data-quality anomalies. All operations are
vectorized pandas/numpy so this stays fast on files approaching 100MB
(no row-by-row Python loops).

No DB access, no LLM calls. See `spec/capabilities/dataset-ingestion.md`
and `spec/agent.md` (`dataset_schema` / `dataset_anomalies` shapes).
"""

from __future__ import annotations

import pandas as pd

from domain.dataset import Anomaly, ColumnProfile, DatasetProfile
from tools.ingestion import ParsedCsv

# Anomaly types, per `spec/data.md`'s `anomalies_json`.
ANOMALY_MISSING_VALUES = "missing_values"
ANOMALY_OUTLIERS = "outliers"
ANOMALY_MIXED_TYPES = "mixed_types"
ANOMALY_INCONSISTENT_FORMAT = "inconsistent_format"
ANOMALY_DUPLICATE_ROWS = "duplicate_rows"

MISSING_VALUE_THRESHOLD_PCT = 5.0  # flag columns with >5% nulls

# String-based anomaly heuristics (mixed-type / inconsistent-format detection)
# scan text values with regex/coercion. On files approaching 100MB these full
# scans dominate profiling time, so above this many non-null values we evaluate
# the heuristic on a deterministic random sample and scale the reported counts.
# This affects ONLY the heuristic anomaly flags -- every numeric summary
# statistic and null count in `profile_dataframe` is still computed over the
# FULL column, so quantitative correctness is never traded for speed.
STRING_SCAN_SAMPLE_SIZE = 50_000
_DATE_FORMAT_PATTERNS: dict[str, str] = {
    "iso_yyyy_mm_dd": r"^\d{4}-\d{2}-\d{2}$",
    "us_mm_dd_yyyy": r"^\d{1,2}/\d{1,2}/\d{4}$",
    "dd_mon_yyyy": r"^\d{1,2}-[A-Za-z]{3}-\d{4}$",
    "dd_mm_yyyy_dot": r"^\d{1,2}\.\d{1,2}\.\d{4}$",
}


def _friendly_dtype(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "string"


def profile_dataframe(df: pd.DataFrame) -> list[ColumnProfile]:
    """Compute a per-column schema profile: dtype, null_pct, distinct_count,
    and (for numeric columns) min/max/mean/std.
    """
    row_count = len(df)
    profiles: list[ColumnProfile] = []

    for column in df.columns:
        series = df[column]
        null_count = int(series.isna().sum())
        null_pct = round((null_count / row_count) * 100, 2) if row_count else 0.0
        distinct_count = int(series.nunique(dropna=True))
        dtype = _friendly_dtype(series)

        min_v = max_v = mean_v = std_v = None
        if dtype in ("integer", "float"):
            numeric = pd.to_numeric(series, errors="coerce")
            if numeric.notna().any():
                min_v = float(numeric.min())
                max_v = float(numeric.max())
                mean_v = float(numeric.mean())
                std_v = float(numeric.std()) if row_count > 1 else 0.0

        profiles.append(
            ColumnProfile(
                name=str(column),
                dtype=dtype,
                null_count=null_count,
                null_pct=null_pct,
                distinct_count=distinct_count,
                min=min_v,
                max=max_v,
                mean=mean_v,
                std=std_v,
            )
        )

    return profiles


def _missing_value_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    row_count = len(df)
    if row_count == 0:
        return anomalies

    null_pcts = (df.isna().sum() / row_count) * 100
    for column, pct in null_pcts.items():
        if pct <= MISSING_VALUE_THRESHOLD_PCT:
            continue
        if pct >= 50:
            severity = "high"
        elif pct >= 20:
            severity = "medium"
        else:
            severity = "low"
        anomalies.append(
            Anomaly(
                column=str(column),
                type=ANOMALY_MISSING_VALUES,
                severity=severity,
                description=f"{round(pct, 1)}% missing values",
            )
        )
    return anomalies


def _outlier_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for column in df.columns:
        series = df[column]
        if not (pd.api.types.is_integer_dtype(series) or pd.api.types.is_float_dtype(series)):
            continue
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if len(numeric) < 4:
            continue

        q1 = numeric.quantile(0.25)
        q3 = numeric.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        outlier_mask = (numeric < lower_bound) | (numeric > upper_bound)
        outlier_count = int(outlier_mask.sum())
        if outlier_count == 0:
            continue

        pct = (outlier_count / len(numeric)) * 100
        severity = "high" if pct >= 5 else "medium" if pct >= 1 else "low"
        anomalies.append(
            Anomaly(
                column=str(column),
                type=ANOMALY_OUTLIERS,
                severity=severity,
                description=(
                    f"{outlier_count} outlier value(s) detected outside the "
                    f"expected range [{lower_bound:.2f}, {upper_bound:.2f}] "
                    "(IQR method)"
                ),
            )
        )
    return anomalies


def _scan_series(non_null: pd.Series) -> tuple[pd.Series, int]:
    """Return a (possibly sampled) view of `non_null` for a text-heuristic
    scan, plus the FULL non-null length so counts can be scaled back up.

    For large columns this caps the expensive regex/coercion work at
    ``STRING_SCAN_SAMPLE_SIZE`` values (deterministic random sample) while
    leaving numeric summary statistics -- computed elsewhere over the full
    column -- untouched.
    """
    total = len(non_null)
    if total > STRING_SCAN_SAMPLE_SIZE:
        return non_null.sample(n=STRING_SCAN_SAMPLE_SIZE, random_state=0), total
    return non_null, total


def _mixed_type_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for column in df.columns:
        series = df[column]
        if not pd.api.types.is_string_dtype(series):
            continue

        non_null = series.dropna()
        total = len(non_null)
        if total == 0:
            continue

        scanned, total = _scan_series(non_null)
        scanned_len = len(scanned)
        as_str = scanned.astype(str)
        numeric_parsed = pd.to_numeric(as_str, errors="coerce")
        numeric_frac = float(numeric_parsed.notna().mean())
        # Scale sampled fractions back to full-column count estimates.
        numeric_count = int(round(numeric_frac * total))
        non_numeric_count = total - numeric_count
        sampled_numeric = int(numeric_parsed.notna().sum())
        sampled_non_numeric = scanned_len - sampled_numeric

        if sampled_numeric > 0 and sampled_non_numeric > 0:
            pct_mixed = (min(numeric_frac, 1 - numeric_frac)) * 100
            severity = "high" if pct_mixed >= 20 else "medium" if pct_mixed >= 5 else "low"
            anomalies.append(
                Anomaly(
                    column=str(column),
                    type=ANOMALY_MIXED_TYPES,
                    severity=severity,
                    description=(
                        f"Column mixes numeric-looking values ({numeric_count}) "
                        f"and non-numeric text values ({non_numeric_count})"
                    ),
                )
            )
    return anomalies


def _inconsistent_format_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for column in df.columns:
        series = df[column]
        if not pd.api.types.is_string_dtype(series):
            continue

        non_null = series.dropna().astype(str)
        if len(non_null) == 0:
            continue

        scanned, _total = _scan_series(non_null)

        matched_formats: dict[str, int] = {}
        matched_mask = pd.Series(False, index=scanned.index)
        for fmt_name, pattern in _DATE_FORMAT_PATTERNS.items():
            mask = scanned.str.match(pattern)
            count = int(mask.sum())
            if count > 0:
                matched_formats[fmt_name] = count
                matched_mask |= mask

        total_matched = int(matched_mask.sum())
        if total_matched == 0:
            continue

        # Only treat this as a date-like column if a meaningful share of
        # values look like a date at all.
        if total_matched / len(scanned) < 0.5:
            continue

        distinct_formats = {name for name, count in matched_formats.items() if count > 0}
        if len(distinct_formats) > 1:
            anomalies.append(
                Anomaly(
                    column=str(column),
                    type=ANOMALY_INCONSISTENT_FORMAT,
                    severity="medium",
                    description=f"{len(distinct_formats)} date formats detected",
                )
            )
    return anomalies


def _duplicate_row_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    duplicate_count = int(df.duplicated().sum())
    if duplicate_count == 0:
        return []
    pct = (duplicate_count / len(df)) * 100 if len(df) else 0.0
    severity = "high" if pct >= 10 else "medium" if pct >= 2 else "low"
    return [
        Anomaly(
            column="*",
            type=ANOMALY_DUPLICATE_ROWS,
            severity=severity,
            description=f"{duplicate_count} duplicate row(s) detected",
        )
    ]


def detect_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    """Deterministic, non-LLM anomaly scan.

    Covers: missing-value percentage per column, IQR-based numeric
    outliers, mixed/inconsistent dtypes within a column, inconsistent
    date/number formats, and duplicate rows.
    """
    anomalies: list[Anomaly] = []
    anomalies.extend(_missing_value_anomalies(df))
    anomalies.extend(_outlier_anomalies(df))
    anomalies.extend(_mixed_type_anomalies(df))
    anomalies.extend(_inconsistent_format_anomalies(df))
    anomalies.extend(_duplicate_row_anomalies(df))
    return anomalies


def build_dataset_profile(parsed: ParsedCsv) -> DatasetProfile:
    """Combine schema profiling and anomaly detection into the single
    `DatasetProfile` object other slices (API, graph) consume.
    """
    schema = profile_dataframe(parsed.df)
    anomalies = detect_anomalies(parsed.df)
    return DatasetProfile(
        row_count=parsed.row_count,
        column_count=parsed.column_count,
        schema=schema,
        anomalies=anomalies,
        parse_warnings=parsed.warnings,
    )
