"""Unit tests for `src/tools/ingestion.py` -- CSV + Excel parsing.

Covers: a clean CSV, a malformed/ragged CSV (must return a decision, never
crash), an empty file, a duplicate-header CSV, the skip_bad_lines retry path,
and (Phase 3) Excel `.xlsx`/`.xls` parsing through the `parse_file` dispatcher
plus corrupt-Excel handling.
"""

from __future__ import annotations

from pathlib import Path

from domain.dataset import ParseDecision
from tools.ingestion import (
    CHOICE_REUPLOAD,
    CHOICE_SKIP_BAD_LINES,
    ParsedCsv,
    parse_csv,
    parse_excel,
    parse_file,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE_PATH = FIXTURES_DIR / "sample_sales.csv"
XLSX_FIXTURE = FIXTURES_DIR / "sample_sales.xlsx"
XLS_FIXTURE = FIXTURES_DIR / "sample_sales.xls"


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


# --- Phase 3: Excel parsing -------------------------------------------------

EXPECTED_EXCEL_COLUMNS = ["date", "region", "product", "revenue", "quantity"]


def test_parse_file_routes_csv_to_csv_path():
    result = parse_file(str(FIXTURE_PATH))

    assert isinstance(result, ParsedCsv)
    assert result.row_count == 400
    assert result.column_count == 5
    assert list(result.df.columns) == EXPECTED_EXCEL_COLUMNS


def test_parse_file_parses_xlsx_first_sheet():
    result = parse_file(str(XLSX_FIXTURE))

    assert isinstance(result, ParsedCsv)
    # First sheet ("sales") has 5 data rows and 5 columns; the second sheet
    # ("notes") must be ignored.
    assert result.row_count == 5
    assert result.column_count == 5
    assert list(result.df.columns) == EXPECTED_EXCEL_COLUMNS
    # Numeric column survives as numeric, matching the CSV path's contract.
    assert result.df["revenue"].dtype.kind == "f"


def test_parse_excel_directly_matches_dispatcher():
    result = parse_excel(str(XLSX_FIXTURE))

    assert isinstance(result, ParsedCsv)
    assert result.column_count == 5
    assert list(result.df.columns) == EXPECTED_EXCEL_COLUMNS


def test_parse_file_parses_legacy_xls_first_sheet():
    result = parse_file(str(XLS_FIXTURE))

    assert isinstance(result, ParsedCsv)
    assert result.row_count == 5
    assert result.column_count == 5
    assert list(result.df.columns) == EXPECTED_EXCEL_COLUMNS
    assert result.df["revenue"].dtype.kind == "f"


def test_xlsx_and_csv_share_the_same_profile_shape():
    csv_result = parse_file(str(FIXTURE_PATH))
    xlsx_result = parse_file(str(XLSX_FIXTURE))

    assert isinstance(csv_result, ParsedCsv)
    assert isinstance(xlsx_result, ParsedCsv)
    # Same contract fields present and same column set (the row counts differ
    # only because the fixtures hold different numbers of sample rows).
    assert list(csv_result.df.columns) == list(xlsx_result.df.columns)
    assert xlsx_result.column_count == len(xlsx_result.df.columns)
    assert xlsx_result.row_count == len(xlsx_result.df)


def test_corrupt_excel_returns_needs_decision_not_a_crash(tmp_path):
    # Bytes that are not a valid workbook, with an .xlsx extension.
    bad = tmp_path / "corrupt.xlsx"
    bad.write_bytes(b"this is definitely not an excel workbook")

    result = parse_file(str(bad))

    assert isinstance(result, ParseDecision)
    assert result.choices == [CHOICE_REUPLOAD]


def test_empty_excel_file_returns_needs_decision(tmp_path):
    empty = tmp_path / "empty.xlsx"
    empty.write_bytes(b"")

    result = parse_file(str(empty))

    assert isinstance(result, ParseDecision)
    assert "empty" in result.issue.lower()
    assert result.choices == [CHOICE_REUPLOAD]


def test_missing_excel_file_returns_needs_decision(tmp_path):
    result = parse_file(str(tmp_path / "nope.xlsx"))

    assert isinstance(result, ParseDecision)
    assert result.choices == [CHOICE_REUPLOAD]
