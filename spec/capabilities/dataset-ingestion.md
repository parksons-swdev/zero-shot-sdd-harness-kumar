# Capability: Dataset Ingestion

## What It Does

Parses an uploaded tabular file — a CSV or an Excel workbook (`.xlsx`/`.xls`) — profiles its schema and summary statistics, detects data-quality anomalies, and persists the dataset locally — entirely deterministically, with no LLM involved and no raw data ever leaving the machine.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Tabular file | file (`.csv`, `.xlsx`, or `.xls`, up to 100MB) | User upload via `POST /datasets` | yes |
| Malformed-file decision | enum (`skip_bad_lines` \| `reupload`) | User response via `POST /datasets/{id}/decisions` | only when a prior upload returned `needs_decision` |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| `Dataset` record (schema, stats, anomalies, status) | structured profile | `Dataset` table (`spec/data.md`); returned to the frontend Upload screen |
| Structural-issue decision request | `{issue, choices}` | Returned to the frontend when the file can't be cleanly parsed |
| Stored CSV file | file | Local disk (`./data/uploads/<dataset_id>.csv`) |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | Write the uploaded file | Fatal for this request — upload fails with a clear error before any `Dataset` row is created |
| Local SQLite DB | Insert/update the `Dataset` row | Fatal — upload fails with a clear error |

No LLM call is made by this capability — ingestion is a deterministic local pipeline.

## Business Rules

- **Format dispatch (Phase 3):** ingestion routes by file extension via a single `parse_file(file_path)` dispatcher — `.csv` goes through the existing `parse_csv`; `.xlsx` is read via pandas `read_excel(engine="openpyxl")` and legacy `.xls` via `read_excel(engine="xlrd")`, always using the **first sheet** of the workbook. All paths return the **same** `ParsedCsv` (success) or `ParseDecision` (needs-a-user-choice) contract, so every downstream profiling/anomaly/graph consumer operates on the resulting DataFrame identically regardless of source format — no downstream code changes.
- **Excel privacy boundary is identical to CSV:** the Excel path only produces an in-memory DataFrame handled by the same local downstream code; raw rows never reach Gemini (see `spec/architecture.md` → Privacy Boundary).
- A malformed/unreadable Excel workbook (corrupt file, wrong/mismatched extension, empty first sheet, engine failure) produces the **same** structured `ParseDecision` (ask-the-user) as a malformed CSV — never a crash and never a silent guess.
- If the file cannot be parsed as tabular data, or has structural inconsistencies (ragged rows, duplicate/empty header, unreadable encoding), the pipeline **asks the user what to do** — it never silently drops rows, guesses a delimiter, or hard-fails with a raw stack trace.
- Anomaly detection runs once per dataset and covers at minimum: missing-value percentage per column, numeric outliers (IQR-based), mixed/inconsistent dtypes within a column, and inconsistent date/number formats.
- Files up to 100MB must be accepted and profiled; profiling for the largest files must still complete well within the end-to-end 30-second answer budget for the *first* question (Phase 2 hardens this specifically for ~100MB files).
- Every `Dataset` is keyed by a UUID independent of any session, so a future multi-dataset library can reuse this schema without a rewrite (see `spec/data.md`).

## Success Criteria

- [ ] A well-formed CSV produces an accurate schema (correct dtypes, null percentages, distinct counts) and a `status: "parsed"` response.
- [ ] A CSV with a ragged row (wrong field count) returns `status: "needs_decision"` with a specific, human-readable issue description and explicit choices — never a crash, never a silent partial parse.
- [ ] Resolving a `needs_decision` dataset with `skip_bad_lines` re-attempts parsing and either succeeds or returns a new, more specific issue.
- [ ] A fixture CSV with injected nulls, one numeric outlier, and a mixed-format date column produces anomaly entries for all three.
- [ ] A 100MB fixture CSV is accepted and profiled without the request timing out.
- [ ] `parse_file` on a committed `.xlsx` fixture and a committed `.xls` fixture (each the first sheet of a multi-sheet workbook) returns a `ParsedCsv` with the same schema/row/column contract as the equivalent CSV, and downstream profiling produces the same result.
- [ ] A corrupt/unreadable Excel file returns a `ParseDecision` (never raises).
- [ ] `POST /datasets` accepts `.xlsx`/`.xls` uploads and returns the same response envelope as for a CSV; an unsupported extension returns `400`.
