# Capability: Run History

## What It Does

Persists every analysis run as a complete, timestamped audit-trail record — question, generated code, result, anomalies, token usage, cost — and lets the user browse and revisit past analyses exactly as they were originally produced.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Completed/failed/clarification run data | full `Run` + `RunStep` records | Written by Conversational Data Analysis's `persist_run` step | yes |
| List/search query | `{limit, offset}` (Phase 1); `{q, date_from, date_to}` (Phase 2) | `GET /runs` | no |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Paginated run list | list of `{run_id, dataset_filename, question_text, status, estimated_cost_usd, created_at}` | History screen list |
| Full run detail | same shape as a completed `GET /runs/{run_id}` response | History screen detail view (reuses the Analysis Workspace's answer renderer) |

## External Calls

None — reads and writes go through the local SQLite DB only.

## Business Rules

- Every run is recorded, including ones that end in `needs_clarification` or `failed` — nothing is silently dropped from the audit trail.
- A revisited run reproduces its original answer, chart, table, and code identically — the history detail view renders the persisted `Run` fields, it does not re-run the analysis.
- Phase 1 provides the list and detail view, real and functional; the search box and date-range filter are visible but disabled (clearly labelled) until Phase 2 wires them to `GET /runs` query params.

## Success Criteria

- [ ] After asking three questions in a session, all three appear in the history list with correct timestamps and statuses (including one that used clarification, if exercised).
- [ ] Opening a past completed run's detail reproduces the same answer text, chart, table, and code shown when it was first produced.
- [ ] Opening a past failed run's detail shows the same stuck explanation and last-attempted code originally shown.
- [ ] (Phase 2) Searching by a keyword from a specific past question returns only matching runs; filtering by a date range excludes runs outside it.
