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
    await page.getByRole('link', { name: 'History' }).click()
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

    // --- 6. Confirm the two Phase 1 stubs are visible and non-functional ---

    // "Dataset Library" nav item: disabled, clicking does nothing.
    const navStub = page.getByRole('button', { name: /dataset library/i })
    await expect(navStub).toBeVisible()
    await expect(navStub).toBeDisabled()
    const urlBeforeStubClick = page.url()
    await navStub.click({ force: true, trial: false }).catch(() => {
      // Disabled controls may refuse the click entirely — that itself proves non-functionality.
    })
    expect(page.url()).toBe(urlBeforeStubClick)

    // History search/filter controls live on the list view, not the detail
    // view (History is a list/detail swap, not a side-by-side layout) — go
    // back to the list first.
    await page.getByRole('button', { name: /back to history/i }).click()
    const searchBox = page.getByPlaceholder('Search by question text…')
    await expect(searchBox).toBeVisible()
    await expect(searchBox).toBeDisabled()

    const dateFilters = page.locator('input[type="date"]')
    await expect(dateFilters).toHaveCount(2)
    await expect(dateFilters.first()).toBeDisabled()
    await expect(dateFilters.nth(1)).toBeDisabled()
  })
})
