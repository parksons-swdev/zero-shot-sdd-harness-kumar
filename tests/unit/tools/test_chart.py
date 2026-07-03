"""Unit tests for `src/tools/chart.py` — deterministic chart/table derivation.

Covers both shapes that LLM-generated `analyze(df)` code legitimately
produces for a "total X by Y" aggregate:
  - flat, top-level dict (e.g. `Series.to_dict()` returned directly)
  - the same aggregate nested under a descriptive key

Regression target: previously only the nested shape produced a chart; the
flat top-level shape silently fell through to `type: "none"` / `[]`.
"""

from __future__ import annotations

import pandas as pd

from src.tools.chart import build_chart_spec, build_key_numbers, build_table_data


class TestFlatTopLevelAggregate:
    """The exact bug case: analyze() returns `series.to_dict()` directly."""

    FULL_RESULT = {
        "East": 561764.87,
        "North": 1551200.95,
        "South": 735809.3,
        "West": 569350.89,
    }

    def test_chart_spec_is_bar_with_xy(self):
        spec = build_chart_spec(self.FULL_RESULT)
        assert spec["type"] == "bar"
        assert spec["x"], "expected non-empty x for a flat top-level aggregate"
        assert len(spec["x"]) == 4
        assert len(spec["y"]) == 4
        assert set(spec["x"]) == set(self.FULL_RESULT.keys())

    def test_table_data_is_non_empty(self):
        table = build_table_data(self.FULL_RESULT)
        assert table
        assert len(table) == 4
        assert {row["key"] for row in table} == set(self.FULL_RESULT.keys())

    def test_key_numbers_unaffected(self):
        # build_key_numbers scans top-level scalars independently and was
        # already correct before this fix — must not regress.
        assert build_key_numbers(self.FULL_RESULT) == self.FULL_RESULT


class TestNestedUnderKeyAggregate:
    """The previously-working case: analyze() nests the aggregate under a key."""

    FULL_RESULT = {
        "total_revenue_by_region": {"East": 561764.87, "North": 1551200.95},
    }

    def test_chart_spec_is_bar_with_xy(self):
        spec = build_chart_spec(self.FULL_RESULT)
        assert spec["type"] == "bar"
        assert len(spec["x"]) == 2
        assert len(spec["y"]) == 2

    def test_table_data_is_non_empty(self):
        table = build_table_data(self.FULL_RESULT)
        assert table
        assert len(table) == 2


class TestSingleScalarNotChartable:
    """A lone scalar has no groupable dimension — must not become a bogus 1-bar chart."""

    FULL_RESULT = {"total": 1234.5}

    def test_chart_spec_is_none_not_bogus_bar(self):
        spec = build_chart_spec(self.FULL_RESULT)
        # A single scalar isn't a chartable series (no dimension to group
        # by) — "none" is correct here rather than fabricating a 1-bar
        # chart out of a single number.
        assert spec["type"] == "none"

    def test_table_data_is_empty(self):
        assert build_table_data(self.FULL_RESULT) == []

    def test_key_numbers_still_populated(self):
        assert build_key_numbers(self.FULL_RESULT) == {"total": 1234.5}


class TestNestedDataFrameValue:
    def test_dataframe_value_produces_table_and_chart(self):
        df = pd.DataFrame({"region": ["East", "North"], "revenue": [561764.87, 1551200.95]})
        full_result = {"summary": df}
        spec = build_chart_spec(full_result)
        assert spec["type"] == "bar"
        assert len(spec["x"]) == 2
        table = build_table_data(full_result)
        assert table == df.to_dict(orient="records")


class TestNestedSeriesValue:
    def test_series_value_produces_table_and_chart(self):
        series = pd.Series({"East": 561764.87, "North": 1551200.95}, name="revenue")
        full_result = {"revenue_by_region": series}
        spec = build_chart_spec(full_result)
        assert spec["type"] == "bar"
        table = build_table_data(full_result)
        assert table == [{"key": "East", "value": 561764.87}, {"key": "North", "value": 1551200.95}]


class TestNestedListOfDictsValue:
    def test_list_of_dicts_value_produces_table_and_chart(self):
        records = [{"region": "East", "revenue": 561764.87}, {"region": "North", "revenue": 1551200.95}]
        full_result = {"rows": records}
        spec = build_chart_spec(full_result)
        assert spec["type"] == "bar"
        assert build_table_data(full_result) == records


class TestEmptyOrNoneFullResult:
    def test_none_full_result(self):
        assert build_chart_spec(None) == {"type": "none"}
        assert build_table_data(None) == []

    def test_empty_dict_full_result(self):
        assert build_chart_spec({}) == {"type": "none"}
        assert build_table_data({}) == []
