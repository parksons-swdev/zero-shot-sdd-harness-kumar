'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { listRuns, type RunSummary } from '@/lib/api'
import ThemeToggle from '@/components/ThemeToggle'
import UsageSummary from '@/components/UsageSummary'

/**
 * ChatGPT-style collapsible left sidebar (Phase 3) — the primary navigation.
 *
 * Folds in the History feature: it lists the user's most recent analyses and
 * clicking one opens that run in the full History screen (via a `#run-<id>`
 * hash the History page reads). The richer History screen (search + date
 * filters) stays reachable via the "History" link, and "Recent Datasets"
 * reselect and "New analysis" (upload) are first-class sidebar actions. Theme
 * toggle lives in the footer.
 *
 * Accessible names preserved for the e2e specs: a link named "History" and a
 * link named "Recent Datasets".
 */

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const RECENT_LIMIT = 15

function IconMenu() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M3 6h18M3 12h18M3 18h18" />
    </svg>
  )
}

function IconPlus() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  )
}

function IconStack() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  )
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)

  // Refetch the recent-analyses list on mount and whenever the route changes
  // (e.g. after asking a question and navigating), so the sidebar stays fresh.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRuns(RECENT_LIMIT, 0)
      .then(items => {
        if (!cancelled) setRuns(items)
      })
      .catch(() => {
        if (!cancelled) setRuns([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pathname])

  if (collapsed) {
    return (
      <aside className="flex h-full w-14 shrink-0 flex-col items-center gap-3 border-r border-gray-200 bg-gray-50 py-3 dark:border-gray-800 dark:bg-gray-900">
        <button
          type="button"
          onClick={onToggle}
          aria-label="Expand sidebar"
          aria-expanded={false}
          data-testid="sidebar-toggle"
          className="rounded-lg p-2 text-gray-600 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconMenu />
        </button>
        <Link
          href="/"
          aria-label="New analysis"
          title="New analysis"
          className="rounded-lg p-2 text-gray-600 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconPlus />
        </Link>
        <Link
          href="/history"
          aria-label="History"
          title="History"
          className="rounded-lg p-2 text-gray-600 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconClock />
        </Link>
        <Link
          href="/datasets"
          aria-label="Recent Datasets"
          title="Recent Datasets"
          className="rounded-lg p-2 text-gray-600 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconStack />
        </Link>
        <div className="mt-auto">
          <ThemeToggle collapsed />
        </div>
      </aside>
    )
  }

  return (
    <aside
      data-testid="sidebar"
      className="flex h-full w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex items-center justify-between px-3 py-3">
        <span className="text-sm font-semibold tracking-tight text-gray-900 dark:text-gray-100">
          CSV Insight Agent
        </span>
        <button
          type="button"
          onClick={onToggle}
          aria-label="Collapse sidebar"
          aria-expanded={true}
          data-testid="sidebar-toggle"
          className="rounded-lg p-1.5 text-gray-500 transition hover:bg-gray-200 dark:text-gray-400 dark:hover:bg-gray-800"
        >
          <IconMenu />
        </button>
      </div>

      <div className="px-3">
        <Link
          href="/"
          className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm transition hover:bg-gray-100 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
        >
          <IconPlus />
          New analysis
        </Link>
      </div>

      <nav className="mt-3 flex flex-col gap-1 px-3 text-sm">
        <Link
          href="/history"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-gray-700 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconClock />
          History
        </Link>
        <Link
          href="/datasets"
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-gray-700 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <IconStack />
          Recent Datasets
        </Link>
      </nav>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-3">
        <p className="px-1 pb-1 text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">
          Recent analyses
        </p>
        {loading ? (
          <div className="space-y-1.5" data-testid="sidebar-loading">
            {[0, 1, 2, 3].map(i => (
              <div key={i} className="h-8 animate-pulse rounded-lg bg-gray-200 dark:bg-gray-800" />
            ))}
          </div>
        ) : runs.length === 0 ? (
          <p className="px-1 py-2 text-xs text-gray-400 dark:text-gray-500">
            No analyses yet. Upload a file and ask a question.
          </p>
        ) : (
          <ul className="space-y-0.5" data-testid="sidebar-analyses">
            {runs.map(run => (
              <li key={run.run_id}>
                <Link
                  href={`/history/#run-${run.run_id}`}
                  title={run.question_text}
                  className="block truncate rounded-lg px-3 py-2 text-sm text-gray-700 transition hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  {run.question_text}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-gray-200 px-3 py-3 dark:border-gray-800">
        <Link
          href="/history"
          className="mb-2 block rounded-lg px-3 py-1.5 text-center text-xs font-medium text-gray-500 transition hover:bg-gray-200 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
        >
          View all history
        </Link>
        <UsageSummary refreshKey={pathname} />
        <ThemeToggle />
      </div>
    </aside>
  )
}
