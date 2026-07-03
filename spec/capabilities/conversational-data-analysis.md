# Capability: Conversational Data Analysis

## What It Does

Answers a natural-language question about the active dataset by reasoning about intent, writing and locally executing pandas code, observing the result, and iterating on failure — returning a plain-language answer, key numbers, an interactive chart, and a summary table, with every raw-data operation kept strictly local.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Question text | string | User message via `POST /sessions/{id}/messages` | yes |
| Dataset schema/stats/anomalies | structured profile | `Dataset` record (from Dataset Ingestion) | yes |
| Recent conversation history | list of turns | `Message` table, via Conversation Memory | yes |
| Prior attempt context (on retry) | code + sanitized error/result | In-run agent state | only on retry |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Plain-language answer, key numbers, chart spec, summary table | structured result | `Run` record; rendered in the Analysis Workspace |
| Clarifying question | string | `Run.clarification_question`; rendered as an assistant chat message |
| Stuck explanation (attempts + where it broke) | string | `Run.stuck_explanation`; rendered transparently in chat |
| Generated code (all attempts; final one shown) | string | `Run.generated_code`; the collapsible code view |
| Token usage / estimated cost | numbers | `Run.token_input_count`/`token_output_count`/`estimated_cost_usd`; the cost badge |
| Step-by-step trace | list | `RunStep` rows; the step-progress indicator and history detail |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini API | Classify/plan, generate pandas code, decide sufficiency, phrase a stuck explanation, compose the final answer | Phase 1: run marked `failed` with a clear error. Phase 2: timeout + backoff retry before giving up. |
| Local pandas sandbox | Execute the generated code against the real, in-memory DataFrame | Not fatal — routes back into the retry loop; only an unexpected framework-level failure is fatal |

## Business Rules

- Uncertainty is handled in strict priority order: (1) ask a clarifying question if the request is ambiguous; (2) otherwise proceed with a best guess and visibly flag the assumption; (3) if execution fails, show the user exactly what was tried and where it got stuck; (4) before giving up, automatically retry with a genuinely different approach.
- **No raw dataset row ever appears in a Gemini prompt or response** — only schema/column metadata, computed summary statistics, small aggregated results, and generated code. See `spec/architecture.md` → Privacy Boundary for the structural enforcement.
- The chart and table are built deterministically from the full local execution result — the LLM authors the analysis code and the narrative, never the chart/table values directly.
- A single run has a bounded number of code-generation attempts (`max_attempts`, default 3 in Phase 1); Phase 2 raises this with named alternate strategies per retry (simplify the aggregation, change chart type, drop a failing column) rather than blindly repeating.
- Every run — including one that ends in `needs_clarification` or `failed` — is recorded as an auditable `Run`; nothing is silently dropped.
- The end-to-end answer for a well-formed question must complete in under 30 seconds on files up to ~100MB.

## Success Criteria

- [ ] A simple, unambiguous question (e.g. "total revenue by region") returns a correct answer with real numbers, a chart, a table, and the executed code, in under 30 seconds.
- [ ] An ambiguous question (e.g. "how are we doing?") returns `status: needs_clarification` with a specific clarifying question, not a guess.
- [ ] A question the agent can reasonably answer with an assumption (e.g. an undefined but inferable metric) proceeds and the response includes a visible assumption flag.
- [ ] A question referencing a non-existent column triggers at least one retry with a different generated-code approach; if all attempts fail, the response includes a specific, transparent stuck explanation naming what was tried.
- [ ] Inspecting the structured logs of every Gemini call made during a run shows no literal cell value from the dataset — only schema/stats/aggregates/code.

## Deferred

Multi-file joins and cross-dataset questions are out of scope for this capability (see `spec/roadmap.md`); it only ever reasons about the one active dataset in the session.
