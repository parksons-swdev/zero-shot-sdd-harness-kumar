# API

---

## API Style

REST (FastAPI), consumed by the Next.js frontend over `fetch()`. All responses use the standard envelope: `{"data": ..., "error": null}` on success, or a `4xx`/`5xx` with `{"detail": {"code": ..., "message": ...}}` on failure. Progress on a long-running run is surfaced via polling `GET /runs/{run_id}` (no websockets/SSE in Phase 1/2 — the ≤30s budget and single-user scale make polling sufficient).

## Endpoints / Commands

### `POST /datasets`

**Purpose:** Upload a CSV, parse and profile it, and create the session that will hold the resulting conversation.

**Request:** `multipart/form-data` with a `file` field (CSV, up to 100MB).

**Response (parsed successfully):**
```json
{
  "data": {
    "dataset_id": "uuid",
    "session_id": "uuid",
    "status": "parsed",
    "filename": "sales_export.csv",
    "row_count": 5000,
    "column_count": 12,
    "schema": [{"name": "region", "dtype": "string", "null_pct": 0.0, "distinct_count": 4}],
    "anomalies": [{"column": "signup_date", "type": "inconsistent_format", "severity": "medium", "description": "3 date formats detected"}]
  },
  "error": null
}
```

**Response (malformed, needs a decision):**
```json
{
  "data": {
    "dataset_id": "uuid",
    "status": "needs_decision",
    "issue": "Row 42 has 14 fields, expected 12.",
    "choices": ["skip_bad_lines", "reupload"]
  },
  "error": null
}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Not a CSV, file missing, or exceeds the 100MB limit |
| 500 | Local disk write or DB failure |

### `POST /datasets/{dataset_id}/decisions`

**Purpose:** Resolve a `needs_decision` dataset by telling the pipeline what to do (per `spec/capabilities/dataset-ingestion.md`).

**Request:**
```json
{"choice": "skip_bad_lines"}
```

**Response:** same shape as `POST /datasets` on success (now `status: "parsed"` or still `needs_decision` if the retry also fails).

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Unknown `choice` value |
| 404 | `dataset_id` not found or not in `needs_decision` status |

### `GET /datasets/{dataset_id}`

**Purpose:** Fetch a dataset's profile (schema, stats, anomalies) — used to re-render the profile summary.

**Response:** same `data` shape as the parsed `POST /datasets` response.

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Unknown `dataset_id` |

### `GET /datasets` *(Phase 2 — `history-api` slice)*

**Purpose:** List recently uploaded datasets, to support the Phase 2 "recent datasets" reselect flow (replacing the Phase 1 disabled "Dataset Library" stub).

**Response:**
```json
{"data": [{"dataset_id": "uuid", "filename": "sales_export.csv", "row_count": 5000, "created_at": "2026-07-01T10:00:00Z"}], "error": null}
```

### `POST /sessions` *(Phase 2 — `history-api` slice)*

**Purpose:** Start a new session against an already-profiled dataset (the reselect flow), without re-uploading.

**Request:**
```json
{"dataset_id": "uuid"}
```

**Response:**
```json
{"data": {"session_id": "uuid", "dataset_id": "uuid"}, "error": null}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Unknown `dataset_id` |

### `POST /sessions/{session_id}/messages`

**Purpose:** Ask a question (or answer a pending clarifying question) — starts a `Run`.

**Request:**
```json
{"content": "what is the total revenue by region?"}
```

**Response:**
```json
{"data": {"run_id": "uuid", "status": "running"}, "error": null}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 400 | Empty `content`, or `session_id` has no attached dataset |
| 404 | Unknown `session_id` |
| 409 | A run is already in progress for this session |

### `GET /sessions/{session_id}/messages`

**Purpose:** Fetch the full conversation history for a session, for chat rendering and follow-up context.

**Response:**
```json
{"data": [{"role": "user", "content": "what is the total revenue by region?", "run_id": null, "created_at": "..."}, {"role": "assistant", "content": "...", "run_id": "uuid", "created_at": "..."}], "error": null}
```

### `GET /runs/{run_id}`

**Purpose:** Poll a run's progress and fetch its full result once terminal. Used both live (during a question) and from the History detail view (after the fact — same shape).

**Response (in progress):**
```json
{
  "data": {
    "run_id": "uuid", "status": "running",
    "step_count": 3, "total_estimated_steps": 5, "current_step_label": "Running analysis code (attempt 1)",
    "started_at": "2026-07-03T10:00:00Z"
  },
  "error": null
}
```

**Response (completed):**
```json
{
  "data": {
    "run_id": "uuid", "status": "completed",
    "question_text": "what is the total revenue by region?",
    "answer_text": "Total revenue was $1.2M, led by the North region at $420K...",
    "key_numbers": {"total_revenue": 1200000, "top_region": "North"},
    "chart_spec": {"type": "bar", "x": ["North", "South", "East", "West"], "y": [420000, 310000, 280000, 190000]},
    "table_data": [{"region": "North", "revenue": 420000}],
    "generated_code": "def analyze(df):\n    return df.groupby('region')['amount'].sum().to_dict()",
    "assumptions": [],
    "anomalies": [{"column": "signup_date", "type": "inconsistent_format", "severity": "medium", "description": "3 date formats detected"}],
    "retry_count": 0, "step_count": 5, "total_estimated_steps": 5,
    "token_input_count": 1840, "token_output_count": 320, "estimated_cost_usd": 0.0041,
    "started_at": "...", "completed_at": "..."
  },
  "error": null
}
```

**Response (needs clarification):**
```json
{"data": {"run_id": "uuid", "status": "needs_clarification", "clarification_question": "By 'doing well', do you mean revenue growth, order volume, or something else?"}, "error": null}
```

**Response (failed / stuck):**
```json
{"data": {"run_id": "uuid", "status": "failed", "stuck_explanation": "I tried grouping by 'region' and then by 'territory' (attempt 2) but both raised a KeyError — the dataset has no column matching either name. The closest column is 'sales_area'.", "generated_code": "...(last attempt)...", "retry_count": 2}, "error": null}
```

**Error cases:**
| Status | Condition |
|--------|-----------|
| 404 | Unknown `run_id` |

### `GET /runs`

**Purpose:** History listing across all sessions (single local user — no per-user scoping needed).

**Query params (Phase 1):** `limit`, `offset`.
**Query params (Phase 2 — `history-api` slice):** `q` (question-text search), `date_from`, `date_to`.

**Response:**
```json
{"data": [{"run_id": "uuid", "dataset_filename": "sales_export.csv", "question_text": "...", "status": "completed", "estimated_cost_usd": 0.0041, "created_at": "..."}], "error": null}
```

## Authentication

None. This is a single-user, local-only tool; the API is bound to `localhost` and has no login, tokens, or per-user scoping. Adding authentication is explicitly out of scope (see `spec/roadmap.md`).
