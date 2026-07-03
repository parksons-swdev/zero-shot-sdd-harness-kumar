'use client'

import { useState } from 'react'
import HistoryList from '@/components/HistoryList'
import HistoryDetail from '@/components/HistoryDetail'

export default function HistoryPage() {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="mb-1 text-2xl font-bold tracking-tight text-gray-900">History</h1>
      <p className="mb-6 text-sm text-gray-500">
        Browse and revisit past analyses. Selecting a run reproduces its answer exactly as it was
        produced — it does not re-run the analysis.
      </p>

      {selectedRunId ? (
        <HistoryDetail runId={selectedRunId} onBack={() => setSelectedRunId(null)} />
      ) : (
        <HistoryList onSelectRun={setSelectedRunId} />
      )}
    </main>
  )
}
