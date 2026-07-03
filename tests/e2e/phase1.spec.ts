import { test, expect, Page } from '@playwright/test'
import path from 'node:path'

/**
 * Phase 1 primary-journey smoke test for the CSV Insight Agent.
 *
 * Runs against the REAL, already-running stack (real FastAPI backend, real
 * SQLite DB, real Gemini API) at http://localhost:8001/app/ — no mocks. See
 * spec/roadmap.md Phase 1 gate step 5 and `playwright.config.ts` for the
 * precondition (server must already be running; this test does not start
 * or stop it).
 *
 * Covers: upload -> ask -> step-progress -> completed answer (text, chart,
 * table, collapsible code) -> revisit in History (read-only reproduction)
 * -> the two Phase 1 non-functional stubs (Dataset Library nav, History
 * search/filter).
 */

const FIXTURE_CSV = path.join(__dirname, '..', 'fixtures', 'sample_sales.csv')
const QUESTION = 'what is the total revenue by region?'

async function uploadFixtureCsv(page: Page) {
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles(FIXTURE_CSV)

  // Well-formed fixture: expect the profile card, not the malformed-file decision panel.
  await expect(page.getByRole('heading', { name: /profiled/i })).toBeVisible({ timeout: 20_000 })

  await page.getByRole('button', { name: /start asking questions/i }).click()
}

test.describe('Phase 1 — Ask One Question, See the Whole Answer', () => {
  test('upload, ask, watch progress, view full answer, revisit in history, confirm stubs', async ({ page }) => {
    // NOTE: baseURL is 'http://localhost:8001/app/' (the static export's
    // basePath). A leading-slash path (e.g. '/') resolves relative to the
    // origin root per WHATWG URL rules, dropping the '/app' prefix — so we
    // navigate with a relative './' to stay under the configured basePath.
    await page.goto('./')

    // --- 1. Upload the committed fixture CSV ---
    await uploadFixtureCsv(page)

    // The chat workspace should now be visible with the message input enabled.
    const chatInput = page.getByPlaceholder('Ask a question about your dataset…')
    await expect(chatInput).toBeVisible({ timeout: 10_000 })

    // --- 2. Ask the question ---
    await chatInput.fill(QUESTION)
    await page.getByRole('button', { name: /^ask$/i }).click()

    // --- 3. Step-progress indicator appears while the run is in flight ---
    // The optimistic "running" turn is rendered synchronously on submit, so
    // this should be visible immediately (a real, deterministic assertion,
    // not a race against the LLM call itself).
    await expect(page.getByTestId('step-progress')).toBeVisible({ timeout: 5_000 })

    // --- 4. Wait for completion; assert the full answer renders ---
    const completedTurn = page.getByTestId('completed-turn').first()
    await expect(completedTurn).toBeVisible({ timeout: 75_000 })

    // Non-empty plain-language answer text.
    const answerText = await completedTurn.locator('p').first().innerText()
    expect(answerText.trim().length).toBeGreaterThan(0)

    // Interactive chart rendered (Plotly container).
    await expect(completedTurn.getByTestId('chart-view')).toBeVisible()
    await expect(completedTurn.getByTestId('chart-view').locator('.js-plotly-plot')).toBeVisible({ timeout: 10_000 })

    // Summary table rendered with at least one data row.
    const summaryTable = completedTurn.getByTestId('summary-table')
    await expect(summaryTable).toBeVisible()
    const tableRowCount = await summaryTable.locator('tbody tr').count()
    expect(tableRowCount).toBeGreaterThan(0)

    // "View analysis code" collapsible section expands to reveal code text.
    const codeToggle = completedTurn.getByRole('button', { name: /view analysis code/i })
    await expect(codeToggle).toBeVisible()
    await codeToggle.click()
    const codeBlock = completedTurn.locator('pre code')
    await expect(codeBlock).toBeVisible()
    const codeText = await codeBlock.innerText()
    expect(codeText.trim().length).toBeGreaterThan(0)

    // --- 5. Navigate to History, confirm the run appears and reproduces ---
    // Redesign note (Phase 3): the ChatGPT-style sidebar exposes both a "History"
    // nav link and a "View all history" footer link. Match the nav link exactly
    // so the selector stays unambiguous (same real element/behavior as before).
    await page.getByRole('link', { name: 'History', exact: true }).click()
    await expect(page).toHaveURL(/\/history\/?$/)

    const historyList = page.getByTestId('history-list')
    await expect(historyList).toBeVisible({ timeout: 15_000 })

    const historyItem = historyList.getByRole('button', { name: new RegExp(QUESTION.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i') })
    await expect(historyItem).toBeVisible()
    // A timestamp is rendered alongside the question (dataset filename · timestamp · cost).
    await expect(historyItem.getByText('sample_sales.csv')).toBeVisible()

    await historyItem.click()

    const historyDetail = page.getByTestId('history-detail')
    await expect(historyDetail).toBeVisible({ timeout: 10_000 })

    // Reproduces the same answer (read-only replay, not a re-run). The
    // "Answer" section renders as an uppercase label paragraph immediately
    // followed by the answer-text paragraph.
    const historyAnswerLabel = historyDetail.getByText('Answer', { exact: true })
    await expect(historyAnswerLabel).toBeVisible()
    const historyAnswerParagraph = historyAnswerLabel.locator('xpath=following-sibling::p[1]')
    const historyAnswerText = await historyAnswerParagraph.innerText()
    expect(historyAnswerText.trim().length).toBeGreaterThan(0)

    // Reproduces the chart.
    await expect(historyDetail.getByTestId('history-chart')).toBeVisible({ timeout: 10_000 })

    // Reproduces the table.
    await expect(historyDetail.locator('table')).toBeVisible()
    const historyTableRowCount = await historyDetail.locator('table tbody tr').count()
    expect(historyTableRowCount).toBeGreaterThan(0)

    // Reproduces the code, on demand.
    const historyCodeToggle = historyDetail.getByRole('button', { name: /view analysis code/i })
    await expect(historyCodeToggle).toBeVisible()
    await historyCodeToggle.click()
    const historyCodeBlock = historyDetail.locator('pre code')
    await expect(historyCodeBlock).toBeVisible()
    const historyCodeText = await historyCodeBlock.innerText()
    expect(historyCodeText.trim().length).toBeGreaterThan(0)

    // --- 6. Reconciliation with the redesigned DOM (Phase 3) ---
    //
    // In Phase 1 these two surfaces shipped as clearly-labelled, NON-functional
    // stubs: a disabled "Dataset Library" nav item and disabled History
    // search/filter controls. Phase 2 wired both into real features (the stub
    // became the functional "Recent Datasets" picker; search/filter went live)
    // and Phase 3 re-dressed them into the ChatGPT-style sidebar. This section
    // is reconciled in lockstep to assert the redesigned reality — that both
    // are now REAL, enabled, reachable controls. This STRENGTHENS the original
    // stub assertions (functional > disabled); it does not weaken them.

    // History search/filter controls live on the list view, not the detail
    // view (History is a list/detail swap, not a side-by-side layout) — go
    // back to the list first.
    await page.getByRole('button', { name: /back to history/i }).click()

    // History search + date filters are now real, enabled controls (Phase 2
    // wired the Phase 1 stubs live).
    const searchBox = page.getByTestId('history-search')
    await expect(searchBox).toBeVisible()
    await expect(searchBox).toBeEnabled()

    const dateFrom = page.getByTestId('history-date-from')
    const dateTo = page.getByTestId('history-date-to')
    await expect(dateFrom).toBeVisible()
    await expect(dateFrom).toBeEnabled()
    await expect(dateTo).toBeVisible()
    await expect(dateTo).toBeEnabled()

    // The former disabled "Dataset Library — coming soon" nav stub is now the
    // functional "Recent Datasets" picker, reachable from the sidebar. Match
    // the nav link exactly (a collapsed-sidebar icon carries the same
    // accessible name) and confirm it navigates to a real, wired screen.
    const recentDatasetsLink = page.getByRole('link', { name: 'Recent Datasets', exact: true })
    await expect(recentDatasetsLink).toBeVisible()
    await recentDatasetsLink.click()
    await expect(page).toHaveURL(/\/datasets\/?$/)

    // The picker renders either its populated list or its labelled empty state —
    // both prove the feature is real and wired, not a dead stub.
    await expect(
      page.locator('[data-testid="datasets-list"], [data-testid="datasets-empty"]'),
    ).toBeVisible({ timeout: 15_000 })
  })
})
