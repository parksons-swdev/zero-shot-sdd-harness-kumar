# Roadmap

---

## What This Agent Does

The CSV Insight Agent is a personal data-analysis assistant. The user uploads a CSV/spreadsheet export from their own machine and asks natural-language questions about it. The agent answers with a plain-language summary containing key numbers, an interactive chart, and a summary table, and proactively flags anomalies or data-quality issues it notices (missing values, outliers, inconsistent formats) — without being asked. It supports both fast single-shot answers and multi-step reasoning where it writes and runs analysis code, observes the result, and iterates when needed.

## Who Uses It

A single user — the repo owner — a few times a day, when they have a spreadsheet export and a question about it they want answered quickly and trustworthily enough to act on.

## Core Problem Being Solved

Answering an ad-hoc question about a CSV export today means opening a spreadsheet or notebook, writing a formula or a pandas snippet by hand, and manually building a chart — every single time, for a single question. This agent collapses that into: upload, ask, get an answer with the numbers, the chart, and the table, backed by a visible, auditable trail of exactly what was computed and how.

## Success Criteria

- [ ] A well-formed CSV up to 100MB can be uploaded and profiled, and a first question answered end-to-end (answer + key numbers + chart + table + code) in under 30 seconds.
- [ ] An ambiguous question produces a clarifying question instead of a guess; a question the agent proceeds on with an assumption visibly flags that assumption.
- [ ] When the agent's first generated-code attempt fails, it automatically retries with a different approach before surfacing a transparent "here's what I tried and where I got stuck" message.
- [ ] No raw data row ever appears in a prompt or response exchanged with the Gemini API — verified by inspecting logged LLM payloads.
- [ ] Every question asked and answer produced is persisted with a timestamp and can be revisited later in the history view, reproducing the original answer, chart, table, and code.
- [ ] A malformed/unparsable CSV never crashes the agent or silently guesses a fix — it asks the user what to do.

## What This Agent Does NOT Do (Out of Scope)

- Multi-file joins, folder uploads, or querying across more than one dataset at a time — deferred; see Deferred Scope below.
- A dataset "library" with naming, tagging, or long-term dataset management beyond re-opening a recently uploaded dataset — deferred.
- Saving/exporting cleaned or derived datasets as new reusable assets — deferred.
- Exporting analyses to external systems (PDF, Slack, email, BI tools) — not built.
- User accounts, authentication, or multi-user access control — this is a single-user local tool.
- Streaming or distributed processing of multi-gigabyte / millions-of-rows datasets — Phase 2 proves correctness and the 30s budget up to ~100MB; beyond that is out of scope.

## Key Constraints

- **Privacy (non-negotiable):** raw row-level data must never be sent to the Gemini API. Only schema/column metadata, computed summary statistics, small aggregated results, and generated code may appear in LLM prompts or responses. See `spec/architecture.md` → Privacy Boundary.
- **Latency:** answers on files up to ~100MB must complete in under 30 seconds on the happy path.
- **Single user, single active session:** no concurrency/multi-tenant design is required; one analysis run in flight at a time is sufficient.
- **Local-only storage:** uploaded files and the database live on the user's own machine (SQLite + local disk), never uploaded to a third-party store.

## Deferred Scope (explicitly out of Phase 1 and Phase 2)

| Deferred item | Reason | Possible future phase |
|---|---|---|
| Multi-file joins / folder upload | Explicitly out of scope per intake; single-file only for now | Not scheduled — would need a "Phase 3: Multi-Dataset Library" if ever prioritized |
| Dataset library (naming, tagging, deletion, cross-session catalog) | Explicitly deferred; Phase 2 only adds lightweight "recent datasets" reselect, not a library | Same as above |
| Saving/exporting derived/cleaned datasets | Deferred alongside multi-file support | Same as above |
| Export integrations (PDF, Slack, email, BI tools) | Not part of the primary journey | Not scheduled |
| Auth / multi-user access control | Single local user; no such requirement | Not scheduled |

---

## Phases of Development

> **Phase 1 is the smallest first-time-right user-testable win.** It must work perfectly the first time the user tests it — zero rough edges on the tested path. Its backend is minimal but REAL on the one core path (no fake data on the tested path). Its frontend is visually complete: real UI for the one working path PLUS clearly-labelled NON-FUNCTIONAL stubs for everything coming later, so the user sees the vision (a stub must never be mistaken for a bug). Each later phase wires those stubs into real functionality, one increment at a time.

### Phase 1 — Ask One Question, See the Whole Answer

- **Goal:** the user uploads one CSV, asks one question, and gets a real, plain-language answer with key numbers, an interactive chart, and a summary table, plus the executed analysis code in a collapsible section — with step-progress, anomaly flags, token/cost display, and a persisted, revisitable run history. All four uncertainty-handling behaviors (clarify first / best-guess-and-flag / show-where-it-got-stuck / retry-with-a-different-approach) and malformed-CSV handling are real, not stubbed. The privacy boundary (no raw rows to Gemini) is enforced structurally.
- **Independent slices (parallel build units):**
  - `db-schema` (backend) — SQLAlchemy models for `Dataset`, `Session`, `Message`, `Run`, `RunStep` + the initial Alembic migration. Deps: none.
  - `dataset-ingestion` (backend) — pure CSV parsing, schema/statistics profiling, and anomaly-detection logic (malformed-file detection produces a structured decision request, never a crash or silent guess). No DB dependency — takes a file path, returns a profile object. Deps: none.
  - `analysis-graph` (backend) — the LangGraph ask-question graph per `spec/agent.md`: state, nodes, edges, the local pandas sandbox, the Gemini prompts, the privacy-boundary sanitization step. Pure graph logic operating on an in-memory DataFrame + a schema dict; no DB dependency — returns a final state dict. Deps: none.
  - `api-routes` (backend) — FastAPI routers wiring the three slices above together: dataset upload/decision endpoints, ask/message endpoints, run/history endpoints, the graph runner, settings additions (Gemini model env vars, upload dir, max file size). This is the integration layer. Deps: `db-schema`, `dataset-ingestion`, `analysis-graph`.
  - `frontend-upload-chat` (frontend) — upload area, chat workspace (question input, assistant message rendering, clarifying-question rendering, assumption/uncertainty callouts, stuck-point transparency), interactive chart component, collapsible code view, step-progress indicator + elapsed timer, token/cost badge. Built against the documented `spec/api.md` contract. Deps: none (wiring to the live API happens once `api-routes` lands, but the surface is built independently).
  - `frontend-history-nav` (frontend) — history list + detail view (real, revisits a past run's answer/chart/table/code), and a clearly-labelled, non-functional "Dataset Library — coming soon" nav stub. Deps: none.
  - `e2e-tests` (frontend + backend) — Playwright smoke test covering the full primary journey. Authored independently; executed last since it requires the integrated app running. Deps (to run, not to author): `api-routes`, `frontend-upload-chat`, `frontend-history-nav`.
- **Key surfaces / files:**
  - `db-schema`: `src/db/models.py`, `alembic/versions/0001_initial.py`
  - `dataset-ingestion`: `src/tools/ingestion.py`, `src/tools/profiling.py`, `src/domain/dataset.py`, `tests/unit/tools/test_profiling.py`
  - `analysis-graph`: `src/graph/state.py`, `src/graph/nodes.py`, `src/graph/edges.py`, `src/graph/agent.py`, `src/tools/sandbox.py`, `src/prompts/*.md`, `tests/unit/graph/test_agent.py`
  - `api-routes`: `src/api/datasets.py`, `src/api/sessions.py`, `src/api/runs.py`, `src/api/__init__.py`, `src/graph/runner.py`, `src/config/settings.py`, `tests/integration/test_ask_flow.py`
  - `frontend-upload-chat`: `frontend/src/app/page.tsx`, `frontend/src/components/Upload*.tsx`, `frontend/src/components/Chat*.tsx`, `frontend/src/components/Chart*.tsx`, `frontend/src/components/CodeView.tsx`, `frontend/src/components/StepProgress.tsx`
  - `frontend-history-nav`: `frontend/src/app/history/page.tsx`, `frontend/src/components/HistoryList.tsx`, `frontend/src/components/HistoryDetail.tsx`, `frontend/src/components/NavStub.tsx`
  - `e2e-tests`: `tests/e2e/phase1.spec.ts`
- **Gate command:**
  1. `uv run alembic upgrade head` — applies the initial migration to the local SQLite DB (`./data/agent.db`); confirm with `uv run alembic current` (must not be blank).
  2. `uv run pytest tests/unit tests/integration -q` — unit tests for ingestion/profiling/graph nodes, plus an integration test that runs the full ask-question graph against the **real Gemini API** (`AGENT_GEMINI_API_KEY` from `.env`) on a committed fixture CSV (`tests/fixtures/sample_sales.csv`, ~5k rows with intentionally injected nulls, an outlier, and a mixed-format date column). The test asserts: no raw cell values appear in any logged Gemini prompt/response, `chart_spec`/`table_data`/`answer_text` are populated for a simple question, a deliberately ambiguous question yields `status == "needs_clarification"`, and a question referencing a non-existent column triggers at least one retry before either succeeding or reaching `show_stuck_point`.
  3. `cd frontend && pnpm build` — static export builds; built CSS contains real Tailwind utility selectors.
  4. `uv run python -m src` (repo root, after the frontend build) — boots FastAPI serving both the API and the static frontend at `http://localhost:8001/app/` with no import errors.
  5. `npx playwright test tests/e2e/ --reporter=line` — headless smoke: upload the sample CSV, ask "what is the total revenue by region?", observe the step-progress indicator advance, see the rendered answer/chart/table/collapsible code/cost badge, open History and reopen the run to confirm it reproduces identically.
- **How the user tests it (handoff seed):**
  1. Run `cd frontend && pnpm build`, then from the repo root run `uv run python -m src`.
  2. Open `http://localhost:8001/app/`.
  3. Drag in a CSV (the committed sample at `tests/fixtures/sample_sales.csv` works, or the user's own file up to 100MB).
  4. Type a question, e.g. "what is the total revenue by region?" and submit.
  5. Watch the step-progress indicator ("Step 2 of 5" + progress bar + elapsed timer) while it works.
  6. Confirm the answer includes: a plain-language summary, key numbers, an interactive chart (try zooming/panning it), a summary table, and a "View analysis code" section that expands to show the exact pandas code that ran. A small badge under the answer shows token usage and estimated cost.
  7. Try an ambiguous question (e.g. "how are we doing?") and confirm the agent asks a clarifying question rather than guessing.
  8. Click the "History" tab — confirm the question just asked appears with a timestamp; click it and confirm it reproduces the same answer/chart/table/code.
  9. **Labelled stubs (non-functional, by design):** the "Dataset Library" nav item is disabled and marked "coming soon" — clicking it does nothing. The search/filter box on the History screen is visible but disabled — it is wired in Phase 2.

### Phase 2 — Deeper Reasoning, Searchable History & Scale

- **Goal:** the reasoning loop is hardened with multiple distinct retry strategies and per-call timeouts/backoff on Gemini; the History screen's search/filter becomes real; the user can reselect a recently uploaded dataset to start a new question session without re-uploading; and the pipeline is proven to hold its answer quality and the 30-second budget on a large (~80–100MB) file — using the full dataset, not a sample.
- **Independent slices (parallel build units):**
  - `analysis-graph-hardening` (backend) — extends `src/graph/nodes.py` / `src/graph/edges.py` with distinct retry strategies per attempt (e.g. simplify the aggregation, try an alternate chart type, drop a column that caused a type error) up to a higher `max_attempts`, and wraps every Gemini call in `src/llm/client.py` with a timeout + exponential-backoff retry. Deps: none (extends Phase 1 files it already owns).
  - `ingestion-scale` (backend) — extends `src/tools/profiling.py` and `src/tools/sandbox.py` with vectorized, chunk-aware profiling and execution so a ~100MB file still profiles and answers within the 30s budget. Deps: none.
  - `history-api` (backend) — extends `src/api/runs.py` with pagination + question-text search + date-range filters, and `src/api/datasets.py` with a `GET /datasets` "recent datasets" listing endpoint. Deps: none.
  - `frontend-history-search` (frontend) — wires the Phase 1 disabled search/filter controls on the History screen into real, working controls against the new query params. Deps: `history-api`.
  - `frontend-dataset-reselect` (frontend) — replaces the Phase 1 "Dataset Library — coming soon" stub with a functional "Recent Datasets" picker (list + select to start a new session against an existing, already-profiled dataset). Deps: `history-api`.
  - `e2e-tests-phase2` (frontend + backend) — Playwright coverage for the retry-recovery UX, history search, and dataset reselect; a backend integration test proving large-file correctness. Deps (to run): all slices above.
- **Key surfaces / files:**
  - `analysis-graph-hardening`: `src/graph/nodes.py`, `src/graph/edges.py`, `src/llm/client.py`
  - `ingestion-scale`: `src/tools/profiling.py`, `src/tools/sandbox.py`
  - `history-api`: `src/api/runs.py`, `src/api/datasets.py`
  - `frontend-history-search`: `frontend/src/app/history/page.tsx`, `frontend/src/components/HistoryList.tsx`
  - `frontend-dataset-reselect`: `frontend/src/app/datasets/page.tsx`, `frontend/src/components/DatasetPicker.tsx`
  - `e2e-tests-phase2`: `tests/e2e/phase2.spec.ts`, `tests/integration/test_large_file.py`
- **Gate command:**
  1. `uv run pytest tests/unit tests/integration -q` — includes `tests/integration/test_large_file.py`, which generates (at test setup, gitignored output) a ~90MB / ~500,000-row CSV, runs a real aggregation question against it end-to-end via the real Gemini API, asserts completion under 30 seconds, and asserts the aggregate answer computed over the **full file** is numerically different from the same query run against a 1,000-row sample of that file — proving the pipeline processes the whole dataset, not a sample.
  2. `cd frontend && pnpm build`
  3. `uv run python -m src`
  4. `npx playwright test tests/e2e/ --reporter=line` (runs both `phase1.spec.ts` and `phase2.spec.ts`)
- **How the user tests it (handoff seed):**
  1. Ask a question that references a column that doesn't exist, or one that requires reformatting a messy column — confirm the agent's step trace shows it trying a different approach after the first attempt fails, and it either recovers or clearly explains where it got stuck.
  2. Go to History, search by a keyword from a past question, and filter by date — confirm results narrow correctly.
  3. Upload a large CSV (~80–100MB — a generator script is provided at `scripts/make_large_sample.py`) and confirm the answer still arrives in under 30 seconds.
  4. Open "Recent Datasets" (the screen that replaced the "coming soon" stub) and reselect a previously uploaded dataset to ask a new question without re-uploading.
