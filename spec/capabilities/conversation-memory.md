# Capability: Conversation Memory

## What It Does

Keeps the active dataset and the full turn-by-turn question/answer history available within a session, so follow-up questions are answered using prior context, without the user re-uploading the file or re-explaining what they mean.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| New user message | string | `POST /sessions/{id}/messages` | yes |
| Existing session's dataset binding | `dataset_id` | `Session` record | yes |
| Prior messages | list of turns | `Message` table | yes (may be empty for the first question) |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| Updated message list | list of `{role, content, run_id, created_at}` | `Message` table; `GET /sessions/{id}/messages`; chat rendering |
| Recent conversation window | capped list of turns | Fed into Conversational Data Analysis's `load_context` node |

## External Calls

None directly — reads and writes go through the local SQLite DB only.

## Business Rules

- History is scoped per `Session`, which is bound to exactly one `Dataset` at a time (Phase 1/2 — see `spec/roadmap.md` for the deferred multi-dataset library).
- The conversation window fed into the reasoning graph is capped to the most recent N turns (default 10) to keep prompts small; the full history remains available in the DB for chat/history rendering even once dropped from the live prompt window.
- Conversation history survives a page reload for the same session (the frontend re-fetches `GET /sessions/{id}/messages` on load) — it is not held only in browser memory.
- Phase 2 adds the ability to start a *new* session against a *previously uploaded* dataset (the "recent datasets" reselect), which begins a fresh, empty conversation against that dataset's existing profile rather than merging histories.

## Success Criteria

- [ ] A follow-up question that omits context present in the prior turn (e.g. "and what about last quarter?" after "what was total revenue this quarter?") is answered correctly using that prior context.
- [ ] Reloading the browser page for an existing session restores the full prior conversation, not an empty chat.
- [ ] Starting a new session against a reselected dataset (Phase 2) begins with an empty conversation, not the prior session's history.
