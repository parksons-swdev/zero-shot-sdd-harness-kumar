"""Deterministic, local-only tabular ingestion.

Given a file path, attempts to parse it as tabular data with pandas -- a CSV
or an Excel workbook (`.xlsx`/`.xls`, first sheet only). Never raises on a
malformed/ambiguous file and never guesses-and-proceeds on a structural
problem -- it always returns a value: either a `ParsedCsv` (success) or a
`ParseDecision` (needs a user choice).

All formats funnel through the same `ParsedCsv` / `ParseDecision` contract, so
every downstream profiling/anomaly/graph consumer operates on the resulting
DataFrame identically regardless of source format.

No DB access, no LLM calls. See `spec/capabilities/dataset-ingestion.md`.
"""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass

import pandas as pd

from domain.dataset import ParseDecision

# Excel engines by extension. `.xlsx` (and `.xlsm`) via openpyxl; legacy
# `.xls` via xlrd. Anything else routes to the CSV path.
_EXCEL_ENGINES = {
    ".xlsx": "openpyxl",
    ".xlsm": "openpyxl",
    ".xls": "xlrd",
}

# The only two choices the API contract (`spec/data.md` / `spec/api.md`)
# accepts back from the user for a `needs_decision` dataset.
CHOICE_SKIP_BAD_LINES = "skip_bad_lines"
CHOICE_REUPLOAD = "reupload"

_BAD_LINE_RE = re.compile(r"Expected (\d+) fields in line (\d+), saw (\d+)")


@dataclass
class ParsedCsv:
    """A successfully parsed CSV."""

    df: pd.DataFrame
    row_count: int
    column_count: int
    warnings: str | None = None


ParseResult = ParsedCsv | ParseDecision


def parse_file(file_path: str, *, skip_bad_lines: bool = False) -> ParseResult:
    """Parse a tabular file, routing by extension.

    `.xlsx`/`.xlsm`/`.xls` go through `parse_excel`; everything else (notably
    `.csv`) goes through `parse_csv`. Returns the same `ParsedCsv` (success) or
    `ParseDecision` (needs-a-user-choice) contract regardless of format, and
    never raises.

    `skip_bad_lines` only applies to the CSV path (Excel has no ragged-row
    retry semantics); it is accepted here so callers can use one signature for
    both the initial parse and the `skip_bad_lines` decision retry.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _EXCEL_ENGINES:
        return parse_excel(file_path)
    return parse_csv(file_path, skip_bad_lines=skip_bad_lines)


def parse_excel(file_path: str) -> ParseResult:
    """Parse the FIRST sheet of an Excel workbook into a DataFrame.

    Uses openpyxl for `.xlsx`/`.xlsm` and xlrd for legacy `.xls`. Returns a
    `ParsedCsv` on success or a `ParseDecision` (`choices=["reupload"]`) for a
    corrupt/unreadable workbook, an empty workbook, or an empty first sheet.
    Never raises -- any failure is mapped to a `ParseDecision`.
    """
    ext = os.path.splitext(file_path)[1].lower()
    engine = _EXCEL_ENGINES.get(ext, "openpyxl")

    try:
        if not os.path.exists(file_path):
            raise OSError("file does not exist")
        if os.path.getsize(file_path) == 0:
            return ParseDecision(
                issue="The uploaded file is empty.",
                choices=[CHOICE_REUPLOAD],
            )
        # sheet_name=0 -> read only the first sheet as a DataFrame.
        df = pd.read_excel(file_path, sheet_name=0, engine=engine)
    except OSError as exc:
        return ParseDecision(
            issue=f"The file could not be read from disk: {exc}",
            choices=[CHOICE_REUPLOAD],
        )
    except ValueError as exc:
        # Empty workbook (no sheets), bad engine/format mismatch, etc.
        return ParseDecision(
            issue=f"The Excel workbook could not be read: {exc}",
            choices=[CHOICE_REUPLOAD],
        )
    except Exception as exc:  # noqa: BLE001 - defensive: corrupt file, engine error
        return ParseDecision(
            issue=f"The Excel workbook could not be parsed: {exc}",
            choices=[CHOICE_REUPLOAD],
        )

    if df.shape[1] == 0 or df.shape[0] == 0:
        return ParseDecision(
            issue="The workbook's first sheet has no data rows / no columns.",
            choices=[CHOICE_REUPLOAD],
        )

    # Normalize column names to strings so downstream code (which assumes
    # string column labels, as the CSV path yields) behaves identically.
    df.columns = [str(c) for c in df.columns]

    header_issue = _check_excel_header(list(df.columns))
    if header_issue is not None:
        return header_issue

    return ParsedCsv(
        df=df,
        row_count=len(df),
        column_count=len(df.columns),
        warnings=None,
    )


def _check_excel_header(columns: list[str]) -> ParseDecision | None:
    if any(not c.strip() or c.startswith("Unnamed:") for c in columns):
        return ParseDecision(
            issue="The workbook's first sheet has one or more empty column names.",
            choices=[CHOICE_REUPLOAD],
        )
    normalized = [c.strip() for c in columns]
    if len(normalized) != len(set(normalized)):
        return ParseDecision(
            issue="The workbook's first sheet has duplicate column names.",
            choices=[CHOICE_REUPLOAD],
        )
    return None


def parse_csv(file_path: str, *, skip_bad_lines: bool = False) -> ParseResult:
    """Parse a CSV file at `file_path` into a DataFrame.

    Returns a `ParsedCsv` on success, or a `ParseDecision` describing the
    structural issue found and the concrete choices available. Never
    raises -- any parsing failure is caught and turned into a
    `ParseDecision` with `choices=["reupload"]` at minimum.

    `skip_bad_lines=True` is the retry path after the user picks
    "skip_bad_lines" on a `needs_decision` dataset with ragged rows.
    """
    try:
        raw = _read_bytes(file_path)
    except OSError as exc:
        return ParseDecision(
            issue=f"The file could not be read from disk: {exc}",
            choices=[CHOICE_REUPLOAD],
        )

    if len(raw.strip()) == 0:
        return ParseDecision(
            issue="The uploaded file is empty.",
            choices=[CHOICE_REUPLOAD],
        )

    decoded = _decode(raw)
    if isinstance(decoded, ParseDecision):
        return decoded
    text = decoded

    first_line = text.splitlines()[0] if text.splitlines() else ""
    header_issue = _check_header(first_line)
    if header_issue is not None:
        return header_issue

    bad_lines: list[str] = []

    def _capture_bad_line(bad_line: list[str]) -> None:
        bad_lines.append(",".join(bad_line))
        return None  # tell the python engine to skip this line

    try:
        if skip_bad_lines:
            df = pd.read_csv(
                io.StringIO(text),
                sep=None,
                engine="python",
                on_bad_lines=_capture_bad_line,
            )
        else:
            df = pd.read_csv(
                io.StringIO(text),
                sep=None,
                engine="python",
                on_bad_lines="error",
            )
    except pd.errors.ParserError as exc:
        return _decision_from_parser_error(exc)
    except pd.errors.EmptyDataError:
        return ParseDecision(
            issue="The uploaded file has no columns / no data.",
            choices=[CHOICE_REUPLOAD],
        )
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return ParseDecision(
            issue=f"The file could not be parsed as CSV: {exc}",
            choices=[CHOICE_REUPLOAD],
        )

    if len(df.columns) == 0 or len(df) == 0 and len(df.columns) == 0:
        return ParseDecision(
            issue="The uploaded file has no columns / no data.",
            choices=[CHOICE_REUPLOAD],
        )

    single_column_issue = _check_single_column(df, first_line)
    if single_column_issue is not None:
        return single_column_issue

    warnings = None
    if bad_lines:
        warnings = f"Skipped {len(bad_lines)} malformed row(s) during parsing."

    return ParsedCsv(
        df=df,
        row_count=len(df),
        column_count=len(df.columns),
        warnings=warnings,
    )


def _read_bytes(file_path: str) -> bytes:
    with open(file_path, "rb") as fh:
        return fh.read()


def _decode(raw: bytes) -> str | ParseDecision:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ParseDecision(
            issue=(
                "The file's text encoding could not be determined "
                "(it is not valid UTF-8)."
            ),
            choices=[CHOICE_REUPLOAD],
        )


def _check_header(first_line: str) -> ParseDecision | None:
    if not first_line.strip():
        return ParseDecision(
            issue="The file's header row is empty.",
            choices=[CHOICE_REUPLOAD],
        )

    try:
        dialect = csv.Sniffer().sniff(first_line)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    fields = next(csv.reader([first_line], delimiter=delimiter))

    if any(not f.strip() for f in fields):
        return ParseDecision(
            issue="The file's header row contains one or more empty column names.",
            choices=[CHOICE_REUPLOAD],
        )

    normalized = [f.strip() for f in fields]
    if len(normalized) != len(set(normalized)):
        return ParseDecision(
            issue="The file's header row contains duplicate column names.",
            choices=[CHOICE_REUPLOAD],
        )

    return None


def _check_single_column(df: pd.DataFrame, first_line: str) -> ParseDecision | None:
    if len(df.columns) != 1:
        return None

    other_delimiter_counts = {
        ";": first_line.count(";"),
        "\t": first_line.count("\t"),
        "|": first_line.count("|"),
    }
    if any(count > 0 for count in other_delimiter_counts.values()):
        return ParseDecision(
            issue=(
                "Only one column was detected, but the header row contains "
                "characters that suggest a different delimiter was intended."
            ),
            choices=[CHOICE_REUPLOAD],
        )
    return None


def _decision_from_parser_error(exc: pd.errors.ParserError) -> ParseDecision:
    message = str(exc)
    match = _BAD_LINE_RE.search(message)
    if match:
        expected, line_no, saw = match.groups()
        issue = f"Row {line_no} has {saw} fields, expected {expected}."
    else:
        issue = f"The file has inconsistent row structure: {message}"
    return ParseDecision(
        issue=issue,
        choices=[CHOICE_SKIP_BAD_LINES, CHOICE_REUPLOAD],
    )
