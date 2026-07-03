# Capability: UI Experience (ChatGPT-Style Layout & Theming)

## What It Does

Presents the entire app as a polished ChatGPT-style interface — a collapsible left sidebar of past analyses, a centered conversation column with message bubbles, a question box pinned to the bottom, and a dark/light theme that defaults to system preference and persists the user's choice — without regressing any existing functionality.

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Past analyses / sessions list | JSON | `GET /runs` (+ `GET /sessions`) | yes |
| Active conversation | JSON | `GET /sessions/{id}/messages`, `GET /runs/{id}` | yes |
| Theme choice | enum (`dark` \| `light` \| system) | `localStorage` (fallback: `prefers-color-scheme`) | no |

## Outputs

| Output | Type | Destination |
|--------|------|-------------|
| ChatGPT-style rendered UI (sidebar + chat column + pinned input) | rendered DOM | Browser |
| Theme-aware Plotly charts (dark template in dark mode) | rendered chart | Browser |
| Persisted theme preference | `localStorage` entry | Browser local storage |

## External Calls

| System | Operation | On Failure |
|--------|-----------|------------|
| Backend REST API | Same endpoints as Phase 1/2 (no new endpoints) | Existing error states (unreachable banner, inline errors) unchanged |

## Business Rules

- Visual/structural redesign ONLY — every Phase 1/2 feature stays present, working, and reachable: upload (incl. Excel), ask, step-progress, plain-language answer + key numbers + interactive chart + summary table + collapsible "View analysis code" + token/cost badge, anomaly flags, clarifying-question flow, stuck-point transparency, run history (search + date filters), Recent Datasets reselect.
- Left sidebar is collapsible and folds in History navigation (browse/select past runs); the full History screen at `/app/history` stays reachable.
- Question input is pinned to the bottom, disabled while a run is in progress (one run in flight at a time).
- Theme defaults to `prefers-color-scheme` on first visit; an explicit toggle choice is persisted in `localStorage` and wins on reload. Implemented with Tailwind's `darkMode: 'class'` strategy.
- Plotly charts must use a dark template in dark mode.
- All existing `data-testid` hooks and accessible names from `tests/e2e/phase1.spec.ts` / `phase2.spec.ts` are preserved, OR the e2e specs are updated in lockstep by the e2e slice — never delete a test or weaken an assertion.

## Success Criteria

- [ ] The redesigned app renders a collapsible left sidebar, a centered chat column with message bubbles, and a bottom-pinned question input; the sidebar collapses and expands.
- [ ] Toggling the theme switches dark↔light; the choice persists across reload; on cleared `localStorage` the theme follows the OS `prefers-color-scheme`.
- [ ] In dark mode the Plotly chart renders with a dark template.
- [ ] `tests/e2e/phase1.spec.ts` and `tests/e2e/phase2.spec.ts` still pass against the redesigned DOM (selectors preserved or updated in lockstep), asserting the same real behavior.
- [ ] `cd frontend && pnpm build` succeeds and the built CSS contains `dark:` Tailwind variants.
