"""Unit tests for `src/tools/ingestion.py` -- CSV parsing.

Covers: a clean CSV, a malformed/ragged CSV (must return a decision, never
crash), an empty file, a duplicate-header CSV, and the skip_bad_lines retry
path.
"""

from __future__ import annotations

from pathlib import Path

from domain.dataset import ParseDecision
from tools.ingestion import CHOICE_REUPLOAD, CHOICE_SKIP_BAD_LINES, ParsedCsv, parse_csv

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample_sales.csv"


def _write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_bytes(content.encode("utf-8"))
    return str(path)


def test_parses_the_canonical_fixture_csv_cleanly():
    result = parse_csv(str(FIXTURE_PATH))

    assert isinstance(result, ParsedCsv)
    assert result.row_count == 400
    assert result.column_count == 5
    assert list(result.df.columns) == ["date", "region", "product", "revenue", "quantity"]


def test_clean_small_csv_parses_successfully(tmp_path):
    content = "a,b,c\n1,2,3\n4,5,6\n"
    path = _write(tmp_path, "clean.csv", content)

    result = parse_csv(path)

    assert isinstance(result, ParsedCsv)
    assert result.row_count == 2
    assert result.column_count == 3
    assert result.warnings is None


def test_ragged_row_returns_needs_decision_not_a_crash(tmp_path):
    # Header declares 3 fields; row 2 has 4.
    content = "a,b,c\n1,2,3\n4,5,6,7\n8,9,10\n"
    path = _write(tmp_path, "ragged.csv", content)

    result = parse_csv(path)

    assert isinstance(result, ParseDecision)
    assert "field" in result.issue.lower()
    assert CHOICE_SKIP_BAD_LINES in result.choices
    assert CHOICE_REUPLOAD in result.choices


def test_skip_bad_lines_retry_resolves_the_ragged_csv(tmp_path):
    content = "a,b,c\n1,2,3\n4,5,6,7\n8,9,10\n"
    path = _write(tmp_path, "ragged.csv", content)

    first = parse_csv(path)
    assert isinstance(first, ParseDecision)

    retried = parse_csv(path, skip_bad_lines=True)

    assert isinstance(retried, ParsedCsv)
    assert retried.row_count == 2
    assert retried.warnings is not None
    assert "1" in retried.warnings


def test_empty_file_returns_needs_decision_not_a_crash(tmp_path):
    path = _write(tmp_path, "empty.csv", "")

    result = parse_csv(path)

    assert isinstance(result, ParseDecision)
    assert "empty" in result.issue.lower()
    assert result.choices == [CHOICE_REUPLOAD]


def test_duplicate_header_returns_needs_decision(tmp_path):
    content = "a,b,a\n1,2,3\n4,5,6\n"
    path = _write(tmp_path, "dupheader.csv", content)

    result = parse_csv(path)

    assert isinstance(result, ParseDecision)
    assert "duplicate" in result.issue.lower()
    assert result.choices == [CHOICE_REUPLOAD]


def test_missing_file_returns_needs_decision_not_a_crash(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.csv")

    result = parse_csv(missing_path)

    assert isinstance(result, ParseDecision)
    assert result.choices == [CHOICE_REUPLOAD]
