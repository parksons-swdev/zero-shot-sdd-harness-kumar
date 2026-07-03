"""Deterministic chart/table derivation — `build_chart_spec` tool (spec/agent.md).

Builds the frontend chart spec and summary table **from `execution_full_result`
only** (the complete local result). The LLM never sees or produces these
values directly — this keeps the visual output faithful to the real data
even though the narrative answer is composed from a sanitized summary.
"""

from __future__ import annotations

import pandas as pd

from tools.sandbox import json_safe_key

MAX_TABLE_ROWS = 500


def _records_from_value(value) -> list[dict] | None:
    if isinstance(value, pd.DataFrame):
        return value.head(MAX_TABLE_ROWS).to_dict(orient="records")
    if isinstance(value, pd.Series):
        return [{"key": json_safe_key(k), "value": v} for k, v in value.head(MAX_TABLE_ROWS).items()]
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return value[:MAX_TABLE_ROWS]
    if isinstance(value, dict) and value and all(not isinstance(v, (dict, list)) for v in value.values()):
        return [{"key": json_safe_key(k), "value": v} for k, v in value.items()]
    return None


def _is_container(value) -> bool:
    return isinstance(value, (dict, list, pd.DataFrame, pd.Series))


def _first_tabular_value(full_result: dict | None) -> tuple[str | None, list[dict] | None]:
    """Finds the best candidate tabular/aggregate shape in `full_result`.

    Checks two shapes, since LLM-generated `analyze(df)` code legitimately
    produces either one:
      1. `full_result` ITSELF is a flat, multi-entry dict of scalars — the
         analyze() function returned the aggregate (e.g. a groupby Series
         via `.to_dict()`) directly at the top level, e.g.
         `{"East": 561764.87, "North": 1551200.95, ...}`. A single-entry
         flat dict (e.g. `{"total": 1234.5}`) is deliberately excluded here:
         a lone scalar has no groupable dimension and isn't a chartable
         series, so it falls through to the nested-value search (and, if
         nothing tabular is nested either, to `type: "none"`) rather than
         being rendered as a bogus one-bar chart.
      2. A value ONE LEVEL DOWN is tabular (DataFrame/Series/list-of-dicts/
         flat-dict-of-scalars) — the analyze() function nested the aggregate
         under a descriptive key, e.g. `{"total_revenue_by_region": {...}}`.
    """
    if not full_result:
        return None, None

    if len(full_result) > 1 and all(not _is_container(v) for v in full_result.values()):
        return None, [{"key": json_safe_key(k), "value": v} for k, v in full_result.items()][:MAX_TABLE_ROWS]

    for key, value in full_result.items():
        records = _records_from_value(value)
        if records:
            return key, records
    return None, None


def build_table_data(execution_full_result: dict | None) -> list[dict]:
    """Extracts the best candidate tabular result for the summary table."""
    _, records = _first_tabular_value(execution_full_result)
    return records or []


def build_key_numbers(execution_full_result: dict | None) -> dict:
    """Pulls headline scalar numbers out of the full result for the answer card."""
    if not execution_full_result:
        return {}
    return {
        key: value
        for key, value in execution_full_result.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def build_chart_spec(execution_full_result: dict | None) -> dict:
    """Derives a minimal chart spec {type, x, y} from the first
    tabular/aggregate-shaped value in `execution_full_result`, per the
    contract documented in `spec/api.md`
    (`{"type": "bar", "x": [...], "y": [...]}`).

    Never touches the LLM. If nothing chartable is found, returns an empty
    spec (`type: "none"`) — the frontend renders the "no chart available"
    state rather than guessing.
    """
    _, records = _first_tabular_value(execution_full_result)
    if not records:
        return {"type": "none"}

    sample = records[0]
    keys = list(sample.keys())
    if len(keys) < 2:
        return {"type": "table_only"}

    label_field = keys[0]
    value_field = next(
        (k for k in keys[1:] if isinstance(sample[k], (int, float)) and not isinstance(sample[k], bool)),
        None,
    )
    if value_field is None:
        return {"type": "table_only"}

    return {
        "type": "bar",
        # `json_safe_key` also serves to coerce a non-primitive x label (e.g. a
        # Period/Timestamp coming from a DataFrame-records path) to a
        # JSON-serializable value so the stored chart_spec never crashes.
        "x": [json_safe_key(record[label_field]) for record in records],
        "y": [record[value_field] for record in records],
    }
