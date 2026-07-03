# Capability: Dataset Ingestion

## What It Does

Parses an uploaded CSV, profiles its schema and summary statistics, detects data-quality anomalies, and persists the dataset locally — entirely deterministically, with no LLM involved and no raw data ever leaving the machine.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| CSV file | file (up to 100MB) | User upload via `POST /datasets` | yes |
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
