'use client'

import { useEffect, useRef, useState } from 'react'
import { listRuns, ApiError, type RunSummary } from '@/lib/api'
import HistoryFilters, { type HistoryFilterValues } from '@/components/HistoryFilters'

export type HistoryRunSummary = RunSummary

const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 350

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-green-100 text-green-700'
    case 'failed':
      return 'bg-red-100 text-red-700'
    case 'needs_clarification':
      return 'bg-amber-100 text-amber-700'
    case 'running':
      return 'bg-blue-100 text-blue-700'
    default:
      return 'bg-gray-100 text-gray-700'
  }
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function formatCost(cost: number | null): string {
  if (cost === null || cost === undefined) return '—'
  return `$${cost.toFixed(4)}`
}

const EMPTY_FILTERS: HistoryFilterValues = { q: '', dateFrom: '', dateTo: '' }

export default function HistoryList({ onSelectRun }: { onSelectRun: (runId: string) => void }) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  // Raw controlled input values (update on every keystroke for a responsive UI).
  const [filters, setFilters] = useState<HistoryFilterValues>(EMPTY_FILTERS)
  // Debounced snapshot that actually drives the fetch.
  const [appliedFilters, setAppliedFilters] = useState<HistoryFilterValues>(EMPTY_FILTERS)

  // Debounce: whenever the raw filters change, wait for a quiet period before
  // committing them to appliedFilters so we don't fire a request per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      setAppliedFilters(filters)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [filters])

  const hasActiveFilter =
    appliedFilters.q.trim() !== '' ||
    appliedFilters.dateFrom !== '' ||
    appliedFilters.dateTo !== ''

  // Fetch whenever the applied (debounced) filters or the page offset change.
  // A ref guards against out-of-order responses overwriting fresher results.
  const requestSeq = useRef(0)
  useEffect(() => {
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    listRuns(PAGE_SIZE, offset, {
      q: appliedFilters.q,
      date_from: appliedFilters.dateFrom || undefined,
      date_to: appliedFilters.dateTo || undefined,
    })
      .then(items => {
        if (seq !== requestSeq.current) return
        setRuns(items)
        setHasMore(items.length === PAGE_SIZE)
      })
      .catch((err: unknown) => {
        if (seq !== requestSeq.current) return
        setError(
          err instanceof ApiError
            ? err.message
            : "Can't reach the server — is it running?",
        )
      })
      .finally(() => {
        if (seq !== requestSeq.current) return
        setLoading(false)
      })
  }, [appliedFilters, offset])

  // When the applied filters change, jump back to the first page.
  useEffect(() => {
    setOffset(0)
  }, [appliedFilters])

  function handleFilterChange(next: HistoryFilterValues) {
    setFilters(next)
  }

  function handleClear() {
    setFilters(EMPTY_FILTERS)
    setAppliedFilters(EMPTY_FILTERS)
    setOffset(0)
  }

  function retry() {
    // Re-trigger the fetch effect by bumping the sequence via a filter identity change.
    setAppliedFilters(prev => ({ ...prev }))
  }

  const emptyMessage = hasActiveFilter
    ? 'No matching runs. Try a different search or date range.'
    : 'No past runs yet. Ask a question on the Analyze screen to get started.'

  return (
    <div>
      <HistoryFilters values={filters} onChange={handleFilterChange} onClear={handleClear} />

      {loading && (
        <div className="space-y-2" data-testid="history-loading">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-100" />
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}{' '}
          <button className="ml-2 underline" onClick={retry}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div
          className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500"
          data-testid="history-empty"
        >
          {emptyMessage}
        </div>
      )}

      {!loading && !error && runs.length > 0 && (
        <ul className="space-y-2" data-testid="history-list">
          {runs.map(run => (
            <li key={run.run_id}>
              <button
                type="button"
                onClick={() => onSelectRun(run.run_id)}
                className="block w-full rounded-lg border border-gray-200 bg-white p-4 text-left shadow-sm transition hover:border-blue-300 hover:shadow"
              >
                <div className="flex items-start justify-between gap-4">
                  <p className="line-clamp-2 text-sm font-medium text-gray-900">{run.question_text}</p>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(run.status)}`}
                  >
                    {run.status}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                  <span>{run.dataset_filename}</span>
                  <span>·</span>
                  <span>{formatTimestamp(run.created_at)}</span>
                  <span>·</span>
                  <span>{formatCost(run.estimated_cost_usd)}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!loading && !error && (runs.length > 0 || offset > 0) && (
        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={!hasMore}
            onClick={() => setOffset(o => o + PAGE_SIZE)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
