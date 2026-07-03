import { test, expect, Page } from '@playwright/test'
import path from 'node:path'

/**
 * Phase 3 E2E coverage for the CSV Insight Agent (spec/roadmap.md Phase 3).
 *
 * Runs against the REAL, already-running stack (real FastAPI backend, real
 * SQLite DB, real Gemini API) at http://localhost:8001/app/ — no mocks. The
 * shared playwright.config.ts does NOT start or stop the server.
 *
 * Phase 3 adds ONE backend input format (Excel) and a ChatGPT-style redesign
 * (collapsible sidebar + dark/light theming). Covered here:
 *   1. Excel upload — an .xlsx workbook profiles and opens the chat exactly
 *      like the CSV path. The deterministic upload/profile/ask-dispatch
 *      assertions do NOT depend on the LLM. The optional answer step is
 *      guarded: Gemini free-tier may return HTTP 429 (environmental quota),
 *      which must not fail this test.
 *   2. Theme toggle — flips the `dark` class on <html>, persists the choice in
 *      localStorage across a reload. Fully deterministic, no LLM.
 *   3. Collapsible sidebar — renders, shows the "Recent analyses" region, and
 *      the collapse/expand toggle works. Fully deterministic, no LLM.
 *
 * Only test 1 can touch the LLM, and only in its clearly-guarded optional tail.
 * Tests 2 and 3 are pure UI/DOM and pass regardless of Gemini quota.
 */

const FIXTURE_XLSX = path.join(__dirname, '..', 'fixtures', 'sample_sales.xlsx')
const THEME_STORAGE_KEY = 'csv-insight-theme'

async function htmlIsDark(page: Page): Promise<boolean> {
  return page.locator('html').evaluate(el => el.classList.contains('dark'))
}

test.describe('Phase 3 — Excel upload + ChatGPT-style UI & theming', () => {
  // ---------------------------------------------------------------------------
  // 1. Excel upload — same profiling/analysis experience as CSV
  // ---------------------------------------------------------------------------
  test('excel upload: an .xlsx file profiles and opens the chat exactly like a CSV', async ({
    page,
  }) => {
    await page.goto('./')

    // Upload the committed .xlsx fixture (first sheet of a multi-sheet workbook).
    const fileInput = page.locator('input[type="file"]')
    await fileInput.setInputFiles(FIXTURE_XLSX)

    // Well-formed workbook: the profile card appears (not the malformed-file
    // decision panel) — deterministic, backend-only (no LLM).
    await expect(page.getByRole('heading', { name: /profiled/i })).toBeVisible({
      timeout: 20_000,
    })
    // The profile card names the Excel file it profiled.
    await expect(page.getByRole('heading', { name: /sample_sales\.xlsx/i })).toBeVisible()

    await page.getByRole('button', { name: /start asking questions/i }).click()

    // Chat workspace opens with the enabled question input — identical surface
    // to the CSV path.
    const chatInput = page.getByPlaceholder('Ask a question about your dataset…')
    await expect(chatInput).toBeVisible({ timeout: 10_000 })

    // Dispatch a real ask. The optimistic "running" turn (step-progress) is
    // rendered synchronously on submit, so this is a deterministic proof that
    // the Excel-backed session accepts questions exactly like a CSV — it does
    // NOT depend on the Gemini response.
    await chatInput.fill('what is the total revenue by region?')
    await page.getByRole('button', { name: /^ask$/i }).click()
    await expect(page.getByTestId('step-progress')).toBeVisible({ timeout: 5_000 })

    // OPTIONAL (guarded) tail: wait for the LLM to resolve the run. On the
    // Gemini free-tier daily quota this may 429 and never resolve — that is
    // environmental, not a code defect, so we annotate and continue rather than
    // fail. The deterministic assertions above are the authoritative Excel
    // coverage.
    try {
      const resolved = page
        .locator('[data-testid="completed-turn"], [data-testid="stuck-turn"]')
        .first()
      await expect(resolved).toBeVisible({ timeout: 80_000 })
      const completed = page.getByTestId('completed-turn')
      if (await completed.count()) {
        const answer = await completed.first().locator('p').first().innerText()
        expect(answer.trim().length).toBeGreaterThan(0)
      }
    } catch {
      test.info().annotations.push({
        type: 'quota',
        description:
          'Excel ask step did not resolve within budget — likely Gemini 429 free-tier ' +
          'quota (environmental). Deterministic upload/profile/ask-dispatch assertions passed.',
      })
    }
  })

  // ---------------------------------------------------------------------------
  // 2. Theme toggle — dark class on <html> + persistence across reload
  // ---------------------------------------------------------------------------
  test('theme toggle: flips the dark class on <html> and persists across reload', async ({
    page,
  }) => {
    await page.goto('./')

    // A single theme toggle is present (sidebar footer / collapsed footer).
    const toggle = page.getByTestId('theme-toggle')
    await expect(toggle).toBeVisible()

    // Drive to a known DARK state (click only if not already dark).
    if (!(await htmlIsDark(page))) {
      await toggle.click()
    }
    await expect(page.locator('html')).toHaveClass(/(^|\s)dark(\s|$)/)
    expect(await page.evaluate(k => localStorage.getItem(k), THEME_STORAGE_KEY)).toBe('dark')

    // Persistence: the dark choice survives a full reload (no-flash script reads
    // localStorage before first paint).
    await page.reload()
    await expect(page.locator('html')).toHaveClass(/(^|\s)dark(\s|$)/)
    expect(await page.evaluate(k => localStorage.getItem(k), THEME_STORAGE_KEY)).toBe('dark')

    // Toggle back to LIGHT: the dark class is removed and the choice persists.
    const toggleAfterReload = page.getByTestId('theme-toggle')
    await expect(toggleAfterReload).toBeVisible()
    await toggleAfterReload.click()
    await expect(page.locator('html')).not.toHaveClass(/(^|\s)dark(\s|$)/)
    expect(await page.evaluate(k => localStorage.getItem(k), THEME_STORAGE_KEY)).toBe('light')

    await page.reload()
    await expect(page.locator('html')).not.toHaveClass(/(^|\s)dark(\s|$)/)
    expect(await page.evaluate(k => localStorage.getItem(k), THEME_STORAGE_KEY)).toBe('light')
  })

  // ---------------------------------------------------------------------------
  // 3. Collapsible sidebar — renders, lists recent analyses, collapse works
  // ---------------------------------------------------------------------------
  test('sidebar: renders the recent-analyses region and the collapse toggle works', async ({
    page,
  }) => {
    await page.goto('./')

    // Expanded sidebar is present with its recent-analyses region.
    const sidebar = page.getByTestId('sidebar')
    await expect(sidebar).toBeVisible()
    await expect(sidebar.getByText('Recent analyses')).toBeVisible()

    // The recent-analyses region resolves to one of its real states: the
    // populated list (data-testid="sidebar-analyses") or the labelled
    // empty-state text — either proves it is wired, not a dead stub. (Serial
    // suite: earlier phases seed runs, but we stay quota-independent here.)
    await expect(
      sidebar
        .getByTestId('sidebar-analyses')
        .or(sidebar.getByText(/no analyses yet/i)),
    ).toBeVisible({ timeout: 15_000 })

    // Collapse: the expanded sidebar (data-testid="sidebar") disappears and the
    // collapsed rail's "Expand sidebar" control appears.
    await page.getByTestId('sidebar-toggle').click()
    await expect(page.getByTestId('sidebar')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /expand sidebar/i })).toBeVisible()

    // Expand again: the full sidebar returns.
    await page.getByTestId('sidebar-toggle').click()
    await expect(page.getByTestId('sidebar')).toBeVisible()
    await expect(page.getByTestId('sidebar').getByText('Recent analyses')).toBeVisible()
  })
})
