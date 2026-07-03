# UI

---

## UI Type

Web app — a single-page chat-style workspace plus a history screen, served as a Next.js static export at `http://localhost:8001/app/`.

## Views / Screens

### Screen: Upload (entry point)

**Purpose:** Get a CSV in and profiled before the user can ask anything.

**Key elements:**
- Drag-and-drop / click-to-browse upload area, accepts `.csv`, states the 100MB limit.
- Upload progress indicator while the file transfers and is parsed/profiled.
- On success: a dataset profile summary card (row count, column count, and any anomalies already flagged — e.g. "3 columns have missing values, 1 outlier detected in `order_amount`") before the chat opens.
- On a malformed file: a plain-language description of the structural issue found, with explicit choice buttons (e.g. "Skip the bad rows and continue", "Upload a different file") — never a silent guess or a raw stack trace.

**Actions available:**
- Upload a file.
- Resolve a malformed-file decision.
- Proceed to the chat workspace once parsed.

### Screen: Analysis Workspace (main screen — real, Phase 1)

**Purpose:** Ask questions about the active dataset and see the full answer.

**Key elements:**
- A chat thread: the user's questions and the agent's replies, in order. Assistant replies render as one of: a clarifying question, an uncertainty-flagged answer ("Note: I assumed 'revenue' means `total_amount`."), a transparent stuck message (what was tried, where it broke), or a full completed answer.
- A completed answer expands into: a plain-language summary, a **key numbers** block (headline figures), an **interactive chart** (zoom/pan/filter — e.g. drag to zoom a time series, click a legend entry to filter a series out), a **summary table** (sortable columns), and a collapsible **"View analysis code"** section (collapsed by default, monospace when expanded) — never the model's raw reasoning trace, only the executed code.
- While a run is in progress: a step-progress indicator ("Step 3 of 5"), a progress bar, and an elapsed-time counter, shown in place of (or alongside) a "thinking" message.
- A small token-usage / estimated-cost badge under each completed answer (e.g. "~2,160 tokens · $0.0041").
- The message input, disabled while a run is in progress (one run in flight at a time).

**Actions available:**
- Ask a question.
- Answer a pending clarifying question.
- Expand/collapse the analysis code for any answer.
- Interact with the chart (zoom, pan, toggle a series).

### Screen: History (real in Phase 1; search/filter wired in Phase 2)

**Purpose:** Browse and revisit past analyses — the audit trail the user can act on.

**Key elements (Phase 1, real):**
- A reverse-chronological list of past runs: question, dataset filename, timestamp, status, estimated cost.
- Clicking a run opens the same answer renderer used in the Analysis Workspace (summary, key numbers, chart, table, collapsible code) — reproducing the run exactly as it was produced.
- **Labelled stub (Phase 1, non-functional):** a search box and a date-range filter control are visible on this screen but disabled, with a small "coming in a future update" note. They are wired to real filtering in Phase 2 (`frontend-history-search` slice) — this is a stub, not a bug.

**Actions available (Phase 1):**
- Scroll/paginate the list.
- Open a past run's detail.

**Actions added (Phase 2):**
- Search by question text; filter by date range.

### Nav item: "Dataset Library" (Phase 1 labelled stub → Phase 2 "Recent Datasets")

**Purpose (eventual):** let the user come back to a previously uploaded dataset without re-uploading.

**Phase 1:** a disabled nav item labelled "Dataset Library — coming soon." Clicking it does nothing functional — this is an explicitly non-functional, clearly-labelled placeholder so the user sees the vision without mistaking it for a bug.

**Phase 2:** replaced by a functional "Recent Datasets" screen — a list of previously uploaded datasets; selecting one starts a new session against that dataset's existing profile, skipping re-upload and re-profiling.

## Error States

- **Upload errors** (wrong file type, over 100MB limit, disk/DB failure): a clear inline message on the Upload screen; the user can retry immediately.
- **Malformed CSV:** never a generic error — always the specific structural issue plus explicit choices (see Upload screen above).
- **Run failure (`status: failed`):** rendered as the agent's own transparent "here's what I tried and where I got stuck" message in the chat thread, including the last attempted code in the collapsible section — not a generic "something went wrong."
- **Network / server unreachable:** a dismissible banner ("Can't reach the server — is it running?") with a retry action; the message input is disabled until connectivity is restored.
- **Loading states:** the step-progress indicator (Analysis Workspace) and a skeleton/spinner on the History list while it loads.

## Tech Stack

Next.js 15 + React 19, static export (`output: 'export'`, `basePath: '/app'`) served by the FastAPI backend at `/app`; Tailwind CSS v4 for styling; `react-plotly.js` for the interactive chart component (zoom/pan/filter built in); Playwright for the `tests/e2e/` smoke suite covering the primary journey (upload → ask → view answer/chart/table/code → revisit in history).
