'use client'

import DatasetPicker from '@/components/DatasetPicker'

export default function DatasetsPage() {
  return (
    <div className="h-full overflow-y-auto px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <h1 className="mb-1 text-2xl font-bold tracking-tight text-gray-900 dark:text-gray-100">Recent Datasets</h1>
        <p className="mb-6 text-sm text-gray-500 dark:text-gray-400">
          Reopen a previously uploaded dataset to ask new questions — this starts a fresh session
          against its existing profile, with no re-upload or re-profiling.
        </p>
        <DatasetPicker />
      </div>
    </div>
  )
}
