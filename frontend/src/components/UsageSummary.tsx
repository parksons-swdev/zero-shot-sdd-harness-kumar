'use client'

import { useEffect, useState } from 'react'
import { getUsageSummary, type UsageSummary as UsageSummaryData } from '@/lib/api'

/**
 * Sidebar token/cost utilization widget: running totals (all-time) plus an
 * expandable per-run breakdown table. Lives in the Sidebar footer, above the
 * theme toggle.
 */

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function formatCost(n: number): string {
  return `$${n < 0.01 && n > 0 ? n.toFixed(4) : n.toFixed(2)}`
}

function IconChevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export default function UsageSummary({ refreshKey }: { refreshKey?: string | null } = {}) {
  const [usage, setUsage] = useState<UsageSummaryData | null>(null)
  const [expanded, setExpanded] = useState(false)

  // Refetches whenever `refreshKey` changes (the Sidebar passes the current
  // route so a new run's usage shows up after navigating), and once on mount.
  useEffect(() => {
    let cancelled = false
    getUsageSummary()
      .then(data => {
        if (!cancelled) setUsage(data)
      })
      .catch(() => {
        if (!cancelled) setUsage(null)
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  if (!usage || usage.run_count === 0) {
    return null
  }

  const totalTokens = usage.total_input_tokens + usage.total_output_tokens

  return (
    <div data-testid="usage-summary" className="mb-2 rounded-lg border border-gray-200 bg-white text-xs dark:border-gray-700 dark:bg-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        aria-expanded={expanded}
        data-testid="usage-summary-toggle"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="font-medium text-gray-700 dark:text-gray-200">Usage</span>
        <span className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <span data-testid="usage-total-tokens" title={`${totalTokens.toLocaleString()} tokens total`}>
            {formatTokens(totalTokens)} tok
          </span>
          <span aria-hidden="true">·</span>
          <span data-testid="usage-total-cost">{formatCost(usage.total_cost_usd)}</span>
          <IconChevron open={expanded} />
        </span>
      </button>

      {expanded && (
        <div className="border-t border-gray-200 dark:border-gray-700">
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-left" data-testid="usage-breakdown-table">
              <thead>
                <tr className="text-[10px] tracking-wide text-gray-400 uppercase dark:text-gray-500">
                  <th className="px-3 py-1 font-medium">Question</th>
                  <th className="px-2 py-1 text-right font-medium">Tokens</th>
                  <th className="px-3 py-1 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {usage.runs.map(run => (
                  <tr key={run.run_id} className="border-t border-gray-100 dark:border-gray-700/60">
                    <td
                      className="max-w-[9rem] truncate px-3 py-1 text-gray-600 dark:text-gray-300"
                      title={run.question_text}
                    >
                      {run.question_text}
                    </td>
                    <td className="px-2 py-1 text-right whitespace-nowrap text-gray-500 dark:text-gray-400">
                      {formatTokens(run.token_input_count + run.token_output_count)}
                    </td>
                    <td className="px-3 py-1 text-right whitespace-nowrap text-gray-500 dark:text-gray-400">
                      {formatCost(run.estimated_cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
