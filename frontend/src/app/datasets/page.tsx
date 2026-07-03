'use client'

import DatasetPicker from '@/components/DatasetPicker'

export default function DatasetsPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="mb-1 text-2xl font-bold tracking-tight text-gray-900">Recent Datasets</h1>
      <p className="mb-6 text-sm text-gray-500">
        Reopen a previously uploaded dataset to ask new questions — this starts a fresh session
        against its existing profile, with no re-upload or re-profiling.
      </p>
      <DatasetPicker />
    </main>
  )
}
