# Data Model

---

## Storage Technology

SQLite (fixed by intake), local file at `./data/agent.db`, accessed via SQLAlchemy 2.0 with Alembic migrations. Uploaded CSVs are stored on local disk at `./data/uploads/<dataset_id>.csv`; the DB stores metadata and computed results only, never a copy of raw dataset content beyond what a specific analysis result legitimately needs to render (e.g. a table the user explicitly asked for).

Every entity is keyed by a UUID primary key from day one, and `Dataset` and `Session` are already separate, independently-keyed entities — even though Phase 1/2 treat "one dataset per session" as the norm — so that a future multi-dataset library (explicitly deferred, see `spec/roadmap.md`) can be added by relaxing that norm without a schema rewrite.

## Entities

### Entity: Dataset

Represents one uploaded tabular file — a CSV or an Excel workbook (`.xlsx`/`.xls`, first sheet) — and its precomputed profile. Immutable once successfully parsed — a re-upload creates a new `Dataset` row. Source format does not change the schema: Excel is parsed into a DataFrame by the ingestion pipeline (`spec/capabilities/dataset-ingestion.md`) and profiled/stored identically to CSV.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| filename | text | yes | Original uploaded filename (`.csv`, `.xlsx`, or `.xls`) |
| file_path | text | yes | Local disk path to the stored upload (extension preserved) |
| size_bytes | integer | yes | File size at upload time |
| row_count | integer | no | Set once successfully parsed |
| column_count | integer | no | Set once successfully parsed |
| schema_json | JSON | no | Per-column profile: `{name, dtype, null_count, null_pct, distinct_count, min, max, mean, std}` (numeric fields only where applicable) |
| anomalies_json | JSON | no | List of `{column, type, severity, description}` — `type` ∈ `missing_values`, `outliers`, `mixed_types`, `inconsistent_format`, `duplicate_rows` |
| status | text | yes | `uploaded` \| `parsed` \| `needs_decision` \| `failed` |
| parse_warnings | text | no | Human-readable notes when parsing succeeded with caveats |
| created_at | timestamp | yes | Upload time |

### Entity: Session

Represents one browser visit's working context: the active dataset and its conversation.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| dataset_id | UUID (text) | no | FK → `Dataset.id`; nullable to allow a session to exist briefly before a dataset is attached, and to support a future session pointed at a reselected dataset |
| created_at | timestamp | yes | |
| last_active_at | timestamp | yes | Updated on every new message |

### Entity: Message

One turn of the conversation (user question or assistant reply), for conversational memory and history rendering.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| session_id | UUID (text) | yes | FK → `Session.id` |
| role | text | yes | `user` \| `assistant` \| `system` |
| content | text | yes | Message text (the question, the clarifying question, or the plain-language answer) |
| run_id | UUID (text) | no | FK → `Run.id`; set on assistant messages that resulted from a run |
| created_at | timestamp | yes | |

### Entity: Run

One full audit-trail record of a single question being answered — the production-grade record the user "acts on."

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| session_id | UUID (text) | yes | FK → `Session.id` |
| dataset_id | UUID (text) | yes | FK → `Dataset.id` |
| question_text | text | yes | The user's question for this run |
| status | text | yes | `pending` \| `running` \| `needs_clarification` \| `completed` \| `failed` |
| clarification_question | text | no | Set when `status = needs_clarification` |
| assumptions_json | JSON | no | Best-guess flags the agent surfaced |
| generated_code | text | no | The final (successful, or last-attempted) pandas code, shown in the collapsible code view |
| answer_text | text | no | Plain-language summary |
| key_numbers_json | JSON | no | The headline numbers extracted from the result |
| chart_spec_json | JSON | no | Chart type + series data for the frontend chart component |
| table_data_json | JSON | no | Summary table rows |
| anomalies_json | JSON | no | Anomalies relevant to / surfaced during this run |
| stuck_explanation | text | no | Set when the agent exhausted retries — what it tried and where it got stuck |
| retry_count | integer | yes | Number of `generate_code` attempts beyond the first; default 0 |
| step_count | integer | yes | Number of steps completed, for the step-progress indicator; default 0 |
| total_estimated_steps | integer | no | Estimated total steps for this run, for "Step N of M" |
| token_input_count | integer | yes | Summed across all LLM calls this run; default 0 |
| token_output_count | integer | yes | Summed across all LLM calls this run; default 0 |
| estimated_cost_usd | numeric | yes | Computed from token counts and published per-token pricing; default 0 |
| error_message | text | no | Set on `status = failed` from an unexpected/fatal error |
| started_at | timestamp | yes | |
| completed_at | timestamp | no | Set on any terminal status |
| created_at | timestamp | yes | |

### Entity: RunStep

One entry in a run's step-by-step audit trail — powers both the live step-progress indicator and the detailed history view.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID (text) | yes | Primary key |
| run_id | UUID (text) | yes | FK → `Run.id` |
| step_number | integer | yes | 1-based order within the run |
| step_type | text | yes | `load_context` \| `classify_request` \| `ask_clarification` \| `generate_code` \| `execute_code` \| `observe_and_decide` \| `show_stuck_point` \| `finalize` |
| label | text | yes | Human-readable label, e.g. "Writing analysis code (attempt 2)" |
| code_snippet | text | no | Populated for `generate_code`/`execute_code` steps |
| is_error | boolean | yes | Whether this step's execution failed; default false |
| output_summary | text | no | Sanitized summary only — never raw row values |
| created_at | timestamp | yes | |

### Relationships

- `Dataset` 1 —— N `Session` (a dataset may be reused by more than one session; Phase 1/2 typically create one session per upload, Phase 2's "recent datasets" reselect creates a second session against the same dataset).
- `Dataset` 1 —— N `Run` (every run answers a question about exactly one dataset).
- `Session` 1 —— N `Message`.
- `Session` 1 —— N `Run`.
- `Run` 1 —— N `RunStep`.
- `Run` 1 —— 0..1 `Message` (the assistant reply message that carries this run's answer/clarifying question).

## Data Lifecycle

- `Dataset`: created on successful or partial (needs-decision) upload; updated to `parsed` once profiling completes; never deleted or mutated after `parsed` (a new upload creates a new row). No retention/purge policy in Phase 1/2 — single local user, small data volume.
- `Session`: created alongside the first upload of a visit (or via the Phase 2 "recent datasets" reselect flow); `last_active_at` updated on every new message; never deleted.
- `Message`: append-only; created for every user question and every assistant reply (including clarifying questions).
- `Run`: created in `pending` status the moment a question is submitted; updated through `running` → a terminal status (`needs_clarification` / `completed` / `failed`) as the graph executes; never deleted — this is the audit trail.
- `RunStep`: append-only, one row per graph step executed for a run.

## Sensitive Data

Uploaded CSVs may contain data the user considers sensitive (it is their own file). All of it — the file on disk, the DB, `execution_full_result`-derived fields like `table_data_json` — stays local to the user's machine; nothing in this system transmits it elsewhere except the explicit, audited exception of what the Privacy Boundary allows into a Gemini prompt (schema/stats/aggregates/code only — see `spec/architecture.md`). There is no authentication layer because this is a single local user; the SQLite file and upload directory are not exposed on any network interface beyond `localhost`.
