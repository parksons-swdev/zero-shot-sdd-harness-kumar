# Agent

> This graph governs the **ask-a-question** flow only. Dataset upload/profiling is a deterministic pipeline with no LLM-driven branching (see `spec/capabilities/dataset-ingestion.md` and `spec/architecture.md`) and does not need a graph. Every user question (including a follow-up) invokes this graph once, seeded from persisted state (dataset schema, conversation history) — the graph itself is not checkpointed across turns; the database is the cross-turn persistence layer.

---

## Agent Architecture Pattern

**Chosen: Graph (LangGraph)** — a bounded ReAct-style reason → act → observe loop (`harness/patterns/agentic-ai.md` #5 Tool Use, #17 Reasoning/ReAct, #22 LLM-Generated Code Execution), composed with:
- **#13 Human-in-the-Loop** — a clarifying-question exit point when the request is ambiguous.
- **#12 Exception Handling and Recovery** — bounded retry with a different approach on code-execution failure, then a transparent "stuck" report.
- **#8 Memory Management** — recent conversation history and the dataset's precomputed profile are loaded into state at the start of every invocation.
- **#18 Guardrails** — the privacy-boundary sanitization step between code execution and every subsequent LLM call.

This is more than a single deterministic transform (the question requires open-ended code generation and may need multiple attempts), and more than a flat tool-call loop (there's a genuine branch for clarification vs. proceeding, and for retry vs. give-up) — a graph with conditional edges is the right level, not multi-agent (one reasoning role suffices; there is no benefit to separate specialized agents here).

---

## LLM Provider & Model

| Agent / Node | Provider | Model ID | Rationale |
|-------------|----------|----------|-----------|
| `classify_request` | Gemini | `gemini-2.5-flash` | Fast triage: ambiguous vs. proceed. Low latency matters more than depth here. |
| `generate_code` | Gemini | `gemini-3.1-pro` | Writing correct pandas code is the highest-value, quality-critical step. |
| `observe_and_decide` | Gemini | `gemini-2.5-flash` | Short structured decision (success / retry / stuck) over a small sanitized observation — fast model suffices. |
| `show_stuck_point` | Gemini | `gemini-2.5-flash` | Phrasing a transparent explanation from already-known facts — no deep reasoning required. |
| `finalize` | Gemini | `gemini-3.1-pro` | Composing the plain-language summary and integrating anomaly flags is user-facing quality-critical output. |

Both model IDs are read from env vars (`AGENT_LLM_MODEL_FAST`, `AGENT_LLM_MODEL_QUALITY`), defaulting to `gemini-2.5-flash` / `gemini-3.1-pro` respectively, so they can change without a code deploy.

**Fallback behaviour:** every Gemini call goes through `src/llm/client.py`. Phase 1: a call failure sets `state["error"]` and routes to `handle_error`, which marks the `Run` `failed` with a clear message. Phase 2: the client wraps calls with a timeout and exponential-backoff retry (`analysis-graph-hardening` slice) before giving up.

**Prompt strategy:** system/user split per node, loaded from `src/prompts/*.md`. `generate_code` and `classify_request`/`observe_and_decide` use structured (JSON/function-calling) output so the graph can parse `clarification_needed`, `code`, `decision`, etc. reliably rather than scraping prose.

---

## Tools & Tool Calling

| Tool name | Description | Inputs | Output | Side-effects |
|-----------|-------------|--------|--------|--------------|
| `load_dataset_context` | Reads a dataset's precomputed schema/stats/anomalies and loads the real DataFrame into an in-process cache | `dataset_id` | schema dict, anomalies list, in-memory `DataFrame` handle | None (read-only) |
| `execute_pandas_code` | Runs LLM-generated code in a restricted local sandbox against the cached DataFrame | `code: str`, `dataframe handle` | `execution_full_result` (local, may include raw rows), `execution_result` (sanitized, LLM-safe), `execution_error` | None persisted directly; in-memory only until `persist_run` |
| `build_chart_spec` | Deterministically derives a chart spec (type + series) from `execution_full_result` — never from the LLM | aggregated/result data | chart spec (JSON) for the frontend chart component | None |
| `detect_anomalies` | Deterministic, non-LLM anomaly scan (nulls, IQR outliers, mixed dtypes, inconsistent formats) — run once at ingestion, referenced by the graph | schema + DataFrame | anomalies list | None (read-only) |
| `persist_run` | Writes the `Run` and `RunStep` audit-trail rows and appends the assistant `Message` | final state | `run_id` | DB write |

**Tool selection strategy:** deterministic — each node calls exactly the tool(s) named above; the LLM never freely picks a tool, it only produces the *content* (code, decisions, prose) that the fixed node sequence acts on.

**Tool failure handling:** `execute_pandas_code` failures are not fatal — they route back into the reasoning loop (`observe_and_decide`) as a retry signal. `persist_run` failures are fatal (the audit trail is non-negotiable) and route to `handle_error`.

---

## Agent State

```python
class AnalysisState(TypedDict, total=False):
    # Identity
    run_id: str
    session_id: str
    dataset_id: str

    # Input
    question: str                        # the user's latest message
    conversation_history: list[dict]      # recent {role, content} turns, loaded from Message table
    dataset_schema: dict                  # column name -> {dtype, null_pct, distinct_count, min, max, mean, std}
    dataset_anomalies: list[dict]         # precomputed at ingestion: {column, type, severity, description}

    # Uncertainty handling (priority order: clarify > best-guess+flag > show-stuck > retry)
    clarification_needed: bool
    clarification_question: str | None
    assumptions: list[str]                # best-guess flags surfaced to the user

    # Reasoning loop
    plan: str | None
    generated_code: str | None
    code_attempts: list[dict]             # [{attempt, code, error_or_summary}], grows each retry
    attempt_count: int
    max_attempts: int                     # default 3 (Phase 1), raised in Phase 2 with distinct strategies
    execution_result: dict | None         # sanitized — the ONLY thing ever sent back into a Gemini prompt
    execution_full_result: dict | None    # full local result (may include raw rows) — frontend/DB only, never to Gemini
    execution_error: str | None           # sanitized (no literal cell values)
    stuck: bool
    stuck_explanation: str | None

    # Progress / observability
    steps: list[dict]                     # audit trail: {step_number, step_type, label, is_error}
    step_count: int
    total_estimated_steps: int
    token_usage: dict                     # {input_tokens, output_tokens} running total across LLM calls this run
    estimated_cost_usd: float

    # Output
    answer_text: str | None
    key_numbers: dict | None
    chart_spec: dict | None
    table_data: list[dict] | None

    # Control
    status: str                           # pending | needs_clarification | completed | failed
    error: str | None                     # set by any node on fatal failure
```

---

## Nodes / Steps

### `load_context`
**Reads from state:** `dataset_id`, `session_id`
**Writes to state:** `dataset_schema`, `dataset_anomalies`, `conversation_history`, `step_count`, `steps`
**LLM call:** no.
**External calls:** DB read (dataset profile, recent messages); loads the real CSV into an in-process DataFrame cache keyed by `dataset_id` (first access per dataset; cached thereafter).
**Behaviour:** Assembles everything the reasoning nodes need without ever exposing raw rows to anything but the local sandbox.

### `classify_request`
**Reads from state:** `question`, `dataset_schema`, `dataset_anomalies`, `conversation_history`
**Writes to state:** `clarification_needed`, `clarification_question`, `plan`, `assumptions`
**LLM call:** yes — `gemini-2.5-flash`, structured output `{clarification_needed, clarification_question, plan, assumptions}`.
**External calls:** none beyond the Gemini call (prompt contains schema/stats/anomalies/history — never raw rows).
**Behaviour:** Implements uncertainty-handling priorities 1 and 2. If the question is genuinely ambiguous (e.g. undefined metric, missing time range with no sensible default), sets `clarification_needed=True`. Otherwise proceeds with a plan and records any assumption it is making (e.g. "assuming 'revenue' means the `total_amount` column") into `assumptions` so it can be surfaced to the user later.

### `ask_clarification`
**Reads from state:** `clarification_question`
**Writes to state:** `answer_text` (set to the clarifying question), `status="needs_clarification"`
**LLM call:** no (reuses the question generated by `classify_request`).
**Behaviour:** Ends the turn early with a clarifying question instead of guessing.

### `generate_code`
**Reads from state:** `question`, `plan`, `dataset_schema`, `dataset_anomalies`, `code_attempts`, `attempt_count`
**Writes to state:** `generated_code`, `attempt_count += 1`
**LLM call:** yes — `gemini-3.1-pro`, structured output `{code}` (a `def analyze(df: pd.DataFrame) -> dict` function body). On retry, the prompt includes the prior attempt's sanitized error/result and an explicit instruction to try a **different approach** (Phase 2 supplies named alternate strategies: simplify the aggregation, change chart type, drop a column that caused a type error).
**External calls:** none beyond the Gemini call.
**Behaviour:** Produces one candidate analysis function per attempt.

### `execute_code`
**Reads from state:** `generated_code`, cached DataFrame for `dataset_id`
**Writes to state:** `execution_result`, `execution_full_result`, `execution_error`, `steps`
**LLM call:** no.
**External calls:** in-process execution in a restricted sandbox (no network, no filesystem, no `os`/`sys` in scope — only `pandas`/`numpy` and the cached DataFrame), with a wall-clock timeout (~25s) to protect the 30s budget.
**Behaviour:** Runs the generated function against the real DataFrame. Applies the Privacy Boundary classifier: if the result is an aggregate (≤ 20 rows, produced via a reduction) its values pass into `execution_result`; if it is row-level or larger, only its shape/dtype are passed into `execution_result` while the full data goes only into `execution_full_result`. On exception, captures a sanitized traceback (message only, no literal values) into `execution_error`.

### `observe_and_decide`
**Reads from state:** `execution_result`, `execution_error`, `attempt_count`, `max_attempts`
**Writes to state:** `stuck`, `code_attempts` (appends this attempt's sanitized summary)
**LLM call:** yes — `gemini-2.5-flash`, structured output `{sufficient: bool, reason: str}`.
**Behaviour:** Implements uncertainty-handling priority 4 (retry) and the transition to priority 3 (show-stuck). If the result is sufficient → proceed to `finalize`. If not sufficient/errored and `attempt_count < max_attempts` → loop back to `generate_code`. If not sufficient/errored and attempts are exhausted → `show_stuck_point`.

### `show_stuck_point`
**Reads from state:** `code_attempts`
**Writes to state:** `stuck_explanation`, `status="failed"` (pending finalize's transparent write-up)
**LLM call:** yes — `gemini-2.5-flash`, phrases a plain-language summary of what was tried and where it broke, from the already-sanitized `code_attempts` log (never raw data).
**Behaviour:** Implements uncertainty-handling priority 3 — full transparency instead of a silent or generic failure.

### `finalize`
**Reads from state:** `execution_full_result`, `execution_result`, `dataset_anomalies`, `assumptions`, `stuck_explanation`, `token_usage`
**Writes to state:** `answer_text`, `key_numbers`, `chart_spec`, `table_data`, `status="completed"` (or `"failed"` if stuck)
**LLM call:** yes (unless stuck, where the stuck explanation is reused) — `gemini-3.1-pro` composes the plain-language narrative from the sanitized `execution_result` plus any surfaced anomalies/assumptions. `chart_spec` and `table_data` are built by the deterministic `build_chart_spec` tool from `execution_full_result` — the LLM never sees or produces the underlying chart/table values directly.
**Behaviour:** Assembles the full user-facing answer, folding in dataset-level anomalies (from ingestion) and any anomalies newly surfaced by this run's execution (e.g. unexpected NaNs after a computed column).

### `persist_run`
**Reads from state:** entire final state
**Writes to state:** none (terminal)
**LLM call:** no.
**External calls:**

| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite DB | Insert/update `Run` row, insert `RunStep` rows, append assistant `Message` | Fatal — routes to `handle_error`; the audit trail is non-negotiable |

**Behaviour:** Writes the complete audit trail (question, generated code, result, anomalies, token usage, estimated cost, timestamps) so the run is revisitable in history exactly as produced.

### `handle_error`
**Reads from state:** `error`, `run_id`
**Writes to state:** `status="failed"`
**Behaviour:** Catches any node-level fatal exception, logs it with `run_id` context, marks the run failed with a clear message, and ends the graph without crashing the process.

---

## Graph / Flow Topology

```
START
  │
  ▼
load_context ──(error)──► handle_error ──► END
  │
  ▼
classify_request ──(error)──► handle_error ──► END
  │
  ├──(clarification_needed)──► ask_clarification ──► persist_run ──► END
  │
  ▼ (proceed)
generate_code ──(error)──► handle_error ──► END
  │
  ▼
execute_code
  │
  ▼
observe_and_decide
  │
  ├──(sufficient)───────────────► finalize
  ├──(insufficient, attempts < max)──► generate_code   [loop back]
  └──(insufficient, attempts exhausted)──► show_stuck_point ──► finalize
                                                                    │
                                                                    ▼
                                                              persist_run
                                                                    │
                                                                    ▼
                                                                   END
```

**Conditional edges:**

| Source node | Condition | Target |
|-------------|-----------|--------|
| `load_context` | `state["error"]` is not None | `handle_error` |
| `classify_request` | `state["error"]` is not None | `handle_error` |
| `classify_request` | `state["clarification_needed"] is True` | `ask_clarification` |
| `classify_request` | otherwise | `generate_code` |
| `generate_code` | `state["error"]` is not None | `handle_error` |
| `observe_and_decide` | result sufficient | `finalize` |
| `observe_and_decide` | insufficient and `attempt_count < max_attempts` | `generate_code` |
| `observe_and_decide` | insufficient and `attempt_count >= max_attempts` | `show_stuck_point` |

---

## Memory & Context

| Scope | Mechanism | What is stored |
|-------|-----------|----------------|
| **Within a run** | LangGraph state (`AnalysisState`) | All in-progress reasoning/execution data for this one question |
| **Across runs (same session)** | SQLite `Message` + `Run` rows, reloaded into `conversation_history` at `load_context` | Prior questions, prior answers (text), enabling natural follow-ups ("and what about last quarter") |
| **Across runs (dataset)** | SQLite `Dataset` row | The precomputed schema/stats/anomalies, reused by every question against that dataset without re-profiling |
| **Conversation** | Message history (last N turns, not full transcript) | Role + content only — no raw dataset values are ever stored in a `Message` |

**Context window management:** `conversation_history` is capped to the most recent N turns (default 10) when building the `classify_request`/`generate_code` prompts, keeping prompts small and well within the fast/cheap-tier model's context budget; older turns remain in the DB for the history view even once dropped from the live prompt window.

---

## Human-in-the-Loop Checkpoints

| Checkpoint | What is shown to the user | Expected user action | Timeout / default |
|------------|--------------------------|----------------------|-------------------|
| `ask_clarification` | The agent's clarifying question, rendered as an assistant chat message | Answer in the next message, which starts a fresh graph invocation with the clarification appended to history | None — the turn simply ends; the user replies whenever they're ready |
| Malformed-CSV decision (ingestion pipeline, not this graph) | The structural parse issue found, with explicit choices (e.g. "skip bad lines", "upload a different file") | Pick a choice via the API/UI | None — upload stays in `needs_decision` status until the user responds |

---

## Error Handling & Recovery

**Node-level:** each node catches its own exceptions; a caught exception sets `state["error"]` and the node's outgoing conditional edge routes to `handle_error`.

**Graph-level (`handle_error` node):**
- Reads: `state.error`, `state.run_id`
- Updates DB: `Run.status = "failed"`, `Run.error_message`, `Run.completed_at`
- Logs the error with `run_id` context (structured log, no raw data)
- Terminates the graph

**Resume / retry strategy:** a failed run is not resumed in-place — the user simply asks again (a fresh graph invocation, with the failure visible in conversation history for context). Within a single run, `generate_code` → `execute_code` → `observe_and_decide` forms the bounded retry loop described above (`max_attempts`, default 3 in Phase 1, raised with distinct strategies in Phase 2).

**Partial failure:** a failed code-execution attempt is never fatal to the run by itself — it is absorbed by the retry loop. Only an unexpected framework-level exception (DB down, Gemini client raising outside the expected error path) is treated as fatal.

---

## Observability

| Signal | What | Where |
|--------|------|-------|
| **Trace** | One trace per run, one span per node, via `@traceable` (LangSmith) wrapping each LLM-calling node function | LangSmith (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY` from `.env`) |
| **LLM calls** | Prompt (sanitized payload only), output, latency, model, input/output token counts | Structured log (`structlog`, stdout) + `RunStep` rows in DB |
| **Tool calls** | `execute_pandas_code` inputs (code only, never data), success/error, latency | Structured log |
| **Run outcome** | Status, total duration, step count, token usage, estimated cost, error if any | DB (`Run` row) + structured log |

This is wired in Phase 1, not deferred — every ask-question run produces a trace and a structured log line, which also serves as the audit surface for the Privacy Boundary gate assertion (no raw values in any logged Gemini payload).

---

## Concurrency Model

- **Run isolation:** one active run per session at a time — the API rejects (409) a new question while a run for that session is still in progress. This matches the "few times a day, single user" scale; no queue is needed.
- **Parallel nodes within a run:** none — the reasoning loop is inherently sequential (each step depends on the previous one's output).
- **Checkpointing:** none. The graph is invoked fresh per user turn; cross-turn continuity comes from the DB-backed `conversation_history` and `dataset_schema`, not from a LangGraph checkpointer.

---

## Graph Assembly (`src/graph/agent.py`)

```python
from langgraph.graph import StateGraph, END
from graph.state import AnalysisState
from graph.nodes import (
    load_context, classify_request, ask_clarification,
    generate_code, execute_code, observe_and_decide,
    show_stuck_point, finalize, persist_run, handle_error,
)
from graph.edges import (
    after_load_context, after_classify, after_generate_code, after_observe,
)

def _build_graph() -> StateGraph:
    g = StateGraph(AnalysisState)

    for name, fn in [
        ("load_context", load_context),
        ("classify_request", classify_request),
        ("ask_clarification", ask_clarification),
        ("generate_code", generate_code),
        ("execute_code", execute_code),
        ("observe_and_decide", observe_and_decide),
        ("show_stuck_point", show_stuck_point),
        ("finalize", finalize),
        ("persist_run", persist_run),
        ("handle_error", handle_error),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("load_context")

    g.add_conditional_edges("load_context", after_load_context,
        {"classify_request": "classify_request", "handle_error": "handle_error"})

    g.add_conditional_edges("classify_request", after_classify,
        {"ask_clarification": "ask_clarification", "generate_code": "generate_code", "handle_error": "handle_error"})

    g.add_conditional_edges("generate_code", after_generate_code,
        {"execute_code": "execute_code", "handle_error": "handle_error"})

    g.add_edge("execute_code", "observe_and_decide")

    g.add_conditional_edges("observe_and_decide", after_observe,
        {"finalize": "finalize", "generate_code": "generate_code", "show_stuck_point": "show_stuck_point"})

    g.add_edge("show_stuck_point", "finalize")
    g.add_edge("finalize", "persist_run")
    g.add_edge("ask_clarification", "persist_run")
    g.add_edge("persist_run", END)
    g.add_edge("handle_error", END)

    return g.compile()

agentic_ai = _build_graph()
```
