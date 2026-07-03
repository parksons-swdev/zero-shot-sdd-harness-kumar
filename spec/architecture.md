# Architecture

---

## System Overview

The CSV Insight Agent is a local, single-user web application. The user's browser talks to a FastAPI backend running on the user's own machine. The backend parses and profiles uploaded CSV or Excel (`.xlsx`/`.xls`, first sheet) files entirely locally, stores the file and its computed profile on local disk / a local SQLite database, and runs a LangGraph agent that answers natural-language questions about the dataset. The agent may call the Gemini API to reason about the question and to write pandas analysis code, but the Gemini API never receives raw data rows — only schema metadata, computed statistics, small aggregated results, and code. All row-level pandas execution happens locally, in-process, on the backend.

## Component Map

```
Browser (Next.js static export)
    │  fetch() over HTTP
    ▼
FastAPI app  ──────────────────────────────┐
    │                                       │
    ├─ Dataset Ingestion Pipeline           │
    │     (parse CSV/Excel via a parse_file  │
    │      dispatcher → DataFrame, profile   │
    │      schema/stats, detect anomalies —  │
    │      local, no LLM)                    │
    │                                       │
    ├─ LangGraph Ask-Question Agent         │
    │     ├─ Gemini API  ←──────────────────┘  (schema/stats/code ONLY — see Privacy Boundary)
    │     └─ Local Pandas Sandbox (executes generated code against the real DataFrame, in-process)
    │
    └─ SQLite DB (datasets, sessions, messages, runs, run_steps)
          local disk file: ./data/agent.db
          uploaded files:  ./data/uploads/<dataset_id>.<csv|xlsx|xls>
```

## Layers

| Layer | Responsibility |
|-------|----------------|
| Frontend (Next.js) | Upload UI, chat workspace, chart/table rendering, step-progress, history browsing |
| API (FastAPI) | HTTP contract, request validation, session/run orchestration, response envelopes |
| Agent (LangGraph) | Reasoning loop: clarify / plan / generate code / execute / observe / retry / finalize |
| Local Execution Sandbox | Runs LLM-generated pandas code against the real in-memory DataFrame; classifies results as LLM-safe vs frontend-only |
| Ingestion Pipeline | Deterministic CSV parsing, schema/statistics profiling, anomaly detection — no LLM involved |
| Persistence (SQLite) | Datasets, sessions, messages, runs, run steps — the audit trail |

## Data Flow

1. **Trigger:** the user uploads a CSV via the browser.
2. The ingestion pipeline parses the file locally, computes schema + summary statistics + anomalies, and persists a `Dataset` row plus the raw file on local disk. If the file is structurally malformed, the pipeline returns a decision request to the user instead of guessing (see `spec/capabilities/dataset-ingestion.md`).
3. A `Session` is created, bound to the dataset. The user submits a question, which is appended to the session's `Message` history and starts a `Run`.
4. The LangGraph agent (`spec/agent.md`) loads the dataset's schema/stats/anomalies (never raw rows) plus recent conversation history, then reasons about the question — clarifying if ambiguous, otherwise planning and writing pandas code.
5. The generated code executes locally against the real DataFrame in the sandbox. The sandbox produces two outputs: a full, potentially row-level result for the frontend, and a sanitized, aggregate-only observation for the next LLM call (see Privacy Boundary below). On error, the agent retries with a different approach up to a bounded number of attempts, or transparently reports where it got stuck.
6. **Output:** the agent composes a plain-language answer, key numbers, a chart spec, and a summary table from the full local result; persists the `Run` (and its `RunStep` audit trail) with token usage and estimated cost; and returns the result to the browser, which renders the answer, interactive chart, table, and collapsible code.

## External Dependencies

| Dependency | Purpose | Failure Mode |
|------------|---------|--------------|
| Gemini API | Reasoning: clarify/plan, generate pandas code, compose the natural-language answer | Timeout/error → the LLM-client wrapper retries with backoff (Phase 2); on exhausted retries the run is marked `failed` with a clear, actionable error surfaced to the user — never a silent hang or crash |
| Local filesystem (`./data/uploads/`) | Stores the uploaded CSV so follow-up questions and history revisits don't require re-upload | Disk write failure → upload request fails with a clear error before a `Dataset` row is created |
| Local SQLite DB (`./data/agent.db`) | Persists datasets, sessions, messages, runs, run steps | DB unavailable → API returns 500 with a clear error; the agent does not proceed without a persisted `Run` row (audit trail is non-negotiable) |

---

## Privacy Boundary (non-negotiable)

**Raw data rows must never leave the machine or be sent to the Gemini API.** This is a first-class architectural constraint, not a best-effort guideline.

**What is allowed in a Gemini prompt or response:**
- Column names, inferred dtypes, null counts/percentages, distinct-value counts, and numeric summary statistics (min/max/mean/std/quartiles) computed locally — never individual cell values.
- Small **aggregated** results produced by the locally-executed code — e.g. "total revenue by region: North=120,000, South=98,500, East=…" (≤ 20 grouped rows). An aggregate is the output of a `groupby`/`agg`/`describe`-style reduction over the whole column, not a slice of raw records.
- Row/column counts and dtypes of any intermediate or final result (shape metadata only).
- Sanitized error messages/tracebacks from failed code execution, with any embedded literal values stripped.
- The generated pandas code itself (code is not data).

**What is never allowed in a Gemini prompt or response:**
- Individual raw rows or any slice of the original DataFrame that resembles source records (e.g. "show me the top 10 customers" — the resulting customer-level rows are frontend-only).
- Example/sample cell values from any column, even a handful, for the purpose of "showing the LLM what the data looks like."
- The uploaded file itself, or any file path/content read from it.

**How this is enforced structurally (not just by convention):**
- The local pandas sandbox (`spec/agent.md` → `execute_code` node) always produces **two** outputs from a single code execution: (a) `execution_full_result` — the complete local result, which may contain raw rows, used only to build the chart/table returned to the browser and stored in the DB; and (b) `execution_result` — a sanitized observation built by a deterministic classifier that inspects the shape/origin of the result and either passes through aggregate values (≤ 20 rows, produced by a reduction) or reduces it to shape/dtype/error metadata only. **Only `execution_result` is ever placed into a prompt sent to Gemini.** `execution_full_result` never crosses the LLM-client boundary.
- The LLM-client wrapper (`src/llm/client.py`) is the single choke point for every Gemini call; only the graph nodes that need to reason (classify/generate-code/observe/finalize) call it, each passing an explicitly constructed, already-sanitized prompt payload — nodes never pass a raw DataFrame or file path into a prompt.
- Structured logging of every LLM call (input prompt, output, latency) doubles as an audit surface: the Phase 1 gate integration test asserts, by inspecting these logs, that no value from the fixture CSV's actual cells appears in any logged Gemini payload.
- Dataset ingestion/profiling never calls Gemini at all — it is a deterministic, local-only pipeline (see `spec/capabilities/dataset-ingestion.md`).

---

## Stack

> This project's concrete technology choices. The generic, every-project rules (model-naming, DB driver, dev port, test environment) live in `harness/patterns/tech-stack.md`; this section is only what **this** project picked.

- **Language:** Python 3.12+ (backend/agent); TypeScript (frontend).
- **Agent framework:** LangGraph — the ask-question flow (`spec/agent.md`) is a stateful graph with a bounded reason/act/observe retry loop. Dataset ingestion is a plain deterministic pipeline (no LLM branching), not a graph.
- **LLM provider + model:** Google Gemini. `gemini-3.1-pro` for quality-critical nodes (`generate_code`, `finalize`); `gemini-2.5-flash` for latency-sensitive nodes (`classify_request`, `observe_and_decide`, `show_stuck_point`). Both configurable via env vars — see `spec/agent.md` → LLM Provider & Model.
  > **Assumed:** per-node model split as above; the user's brief fixed the provider (Gemini) but not per-node model choice.
- **Backend:** FastAPI.
- **Database + ORM:** SQLite (fixed by intake) + SQLAlchemy 2.0, migrated with Alembic. Local file at `./data/agent.db`.
- **Frontend:** Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`) served by FastAPI at `/app` — single-origin run/test path per `harness/patterns/tech-stack.md`.
- **Dependency management:** uv (Python) / pnpm (TypeScript).

| Key library | Version | Purpose |
|-------------|---------|---------|
| `langgraph` | latest 0.x | Ask-question agent graph |
| `google-genai` | latest | Gemini API client |
| `pandas` | ^2.2 | Local CSV/Excel parsing, profiling, and sandboxed analysis execution |
| `openpyxl` | latest | Reading `.xlsx` workbooks via `pandas.read_excel` (Phase 3) |
| `xlrd` | latest | Reading legacy `.xls` workbooks via `pandas.read_excel` (Phase 3) |
| `numpy` | ^2.x | Vectorized anomaly detection (outliers, null/format checks) |
| `sqlalchemy` | ^2.0 | ORM for `Dataset`/`Session`/`Message`/`Run`/`RunStep` |
| `alembic` | ^1.13 | Schema migrations |
| `structlog` | latest | Structured request/response/LLM-call logging |
| `langsmith` | latest | Tracing — `@traceable` wraps LLM-calling nodes even though calls go through the raw `google-genai` SDK, not a LangChain chat model |
| `react-plotly.js` / `plotly.js` | latest | Interactive, zoomable/pannable chart rendering in the browser |
| `@playwright/test` | latest | Headless E2E smoke tests |

**Avoid:** LangChain's `ChatGoogleGenerativeAI` wrapper — the skeleton already has a minimal, direct `google-genai` provider (`src/llm/providers/gemini.py`); adding a second LLM abstraction layer on top would be redundant. Avoid any library that would require sending the DataFrame or file contents to a remote service (e.g. hosted "code interpreter" APIs) — all execution stays local per the Privacy Boundary.

## Deployment Model

Runs as a single long-lived local process: `uv run python -m src` boots FastAPI (serving both the JSON API and the pre-built static frontend) on `http://localhost:8001`. No cloud deployment, no containers required for the target use case (a personal tool run by its owner on their own machine).
