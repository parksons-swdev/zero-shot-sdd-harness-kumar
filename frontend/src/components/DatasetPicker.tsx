'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ApiError,
  createSession,
  getDataset,
  listDatasets,
  type DatasetParsed,
  type DatasetSummary,
} from '@/lib/api'

// Key under which a reselected dataset (profile + freshly-created session_id) is
// handed to the Analyze workspace (`/`), which hydrates straight into the chat
// without re-uploading or re-profiling.
export const RESELECT_STORAGE_KEY = 'csv-reselect-dataset'

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export default function DatasetPicker() {
  const router = useRouter()
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // dataset_id currently being opened (session being created), for row-level feedback.
  const [opening, setOpening] = useState<string | null>(null)
  const [openError, setOpenError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    setError(null)
    listDatasets()
      .then(items => {
        // Newest first; defensively sort in case the API order changes.
        const sorted = [...items].sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )
        setDatasets(sorted)
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Can't reach the server — is it running?")
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  async function handleSelect(summary: DatasetSummary) {
    if (opening) return
    setOpening(summary.dataset_id)
    setOpenError(null)
    try {
      // Start a brand-new session against the existing, already-profiled dataset...
      const session = await createSession(summary.dataset_id)
      // ...then fetch the stored profile so the workspace header/profile render
      // exactly as the upload flow would (no re-profiling).
      const profile = await getDataset(summary.dataset_id)
      const hydrated: DatasetParsed = { ...profile, session_id: session.session_id }
      try {
        sessionStorage.setItem(RESELECT_STORAGE_KEY, JSON.stringify(hydrated))
      } catch {
        // sessionStorage unavailable — surface as an open error rather than a silent no-op.
        throw new ApiError('Could not open this dataset in the workspace.', 0)
      }
      router.push('/')
    } catch (err: unknown) {
      setOpening(null)
      setOpenError(
        err instanceof ApiError ? err.message : 'Could not open this dataset. Please try again.',
      )
    }
  }

  if (loading) {
    return (
      <div className="space-y-2" data-testid="datasets-loading">
        {[0, 1, 2].map(i => (
          <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-100 dark:bg-gray-800" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
        {error}{' '}
        <button className="ml-2 underline" onClick={load}>
          Retry
        </button>
      </div>
    )
  }

  if (datasets.length === 0) {
    return (
      <div
        className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
        data-testid="datasets-empty"
      >
        No datasets yet — upload one to get started.
      </div>
    )
  }

  return (
    <div>
      {openError && (
        <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {openError}
        </div>
      )}
      <ul className="space-y-2" data-testid="datasets-list">
        {datasets.map(ds => {
          const isOpening = opening === ds.dataset_id
          return (
            <li key={ds.dataset_id}>
              <button
                type="button"
                disabled={opening !== null}
                onClick={() => handleSelect(ds)}
                className="block w-full rounded-lg border border-gray-200 bg-white p-4 text-left shadow-sm transition hover:border-blue-300 hover:shadow disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-800 dark:bg-gray-900 dark:hover:border-blue-700"
              >
                <div className="flex items-start justify-between gap-4">
                  <p className="line-clamp-1 text-sm font-medium text-gray-900 dark:text-gray-100">{ds.filename}</p>
                  {isOpening && (
                    <span className="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400">Opening…</span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                  <span>{ds.row_count.toLocaleString()} rows</span>
                  <span>·</span>
                  <span>{formatTimestamp(ds.created_at)}</span>
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
