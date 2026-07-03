'use client'

import { useEffect, useState } from 'react'
import HistoryList from '@/components/HistoryList'
import HistoryDetail from '@/components/HistoryDetail'

/**
 * History screen. Selecting a run reproduces its answer read-only.
 *
 * Phase 3: the ChatGPT-style sidebar links a past analysis to `#run-<id>`, so
 * this page reads the URL hash on mount (and on hashchange) to preselect that
 * run — folding the sidebar's fast browse-and-open into the full History
 * screen without changing its list/detail behavior or test hooks.
 */
export default function HistoryPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  useEffect(() => {
    function applyHash() {
      const hash = window.location.hash
      const match = hash.match(/^#run-(.+)$/)
      if (match) setSelectedRunId(match[1])
    }
    applyHash()
    window.addEventListener('hashchange', applyHash)
    return () => window.removeEventListener('hashchange', applyHash)
  }, [])

  function handleBack() {
    setSelectedRunId(null)
    if (window.location.hash) {
      history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <h1 className="mb-1 text-2xl font-bold tracking-tight text-gray-900 dark:text-gray-100">History</h1>
        <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
          Browse and revisit past analyses. Selecting a run reproduces its answer exactly as it was
          produced — it does not re-run the analysis.
        </p>

        {selectedRunId ? (
          <HistoryDetail runId={selectedRunId} onBack={handleBack} />
        ) : (
          <HistoryList onSelectRun={setSelectedRunId} />
        )}
      </div>
    </div>
  )
}
