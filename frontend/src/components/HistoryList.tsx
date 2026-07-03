'use client'

import { useEffect, useState, useCallback } from 'react'

export interface HistoryRunSummary {
  run_id: string
  dataset_filename: string
  question_text: string
  status: string
  estimated_cost_usd: number | null
  created_at: string
}

const PAGE_SIZE = 20

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

export default function HistoryList({ onSelectRun }: { onSelectRun: (runId: string) => void }) {
  const [runs, setRuns] = useState<HistoryRunSummary[]>([])
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  const load = useCallback(async (nextOffset: number) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/runs?limit=${PAGE_SIZE}&offset=${nextOffset}`)
      const body = await res.json()
      if (!res.ok) {
        throw new Error(body?.detail?.message ?? `Request failed (${res.status})`)
      }
      const items: HistoryRunSummary[] = body.data ?? []
      setRuns(items)
      setHasMore(items.length === PAGE_SIZE)
      setOffset(nextOffset)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Can't reach the server — is it running?")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(0)
  }, [load])

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center">
          <div className="group relative flex-1">
            <input
              type="search"
              disabled
              placeholder="Search by question text…"
              title="Search — coming in a future update"
              className="w-full cursor-not-allowed rounded-lg border border-dashed border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-400 placeholder:text-gray-400"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              disabled
              title="Date range filter — coming in a future update"
              className="cursor-not-allowed rounded-lg border border-dashed border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-400"
            />
            <span className="text-xs text-gray-400">to</span>
            <input
              type="date"
              disabled
              title="Date range filter — coming in a future update"
              className="cursor-not-allowed rounded-lg border border-dashed border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-400"
            />
          </div>
        </div>
      </div>
      <p className="mb-4 text-xs text-gray-400">
        Search and date filtering are coming in a future update — not available yet.
      </p>

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
          <button className="ml-2 underline" onClick={() => load(offset)}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500">
          No past runs yet. Ask a question on the Analyze screen to get started.
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
            onClick={() => load(Math.max(0, offset - PAGE_SIZE))}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={!hasMore}
            onClick={() => load(offset + PAGE_SIZE)}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
