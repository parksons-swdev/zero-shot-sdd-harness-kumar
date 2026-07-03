'use client'

import { DatasetParsed } from '@/lib/api'

interface UploadProfileCardProps {
  dataset: DatasetParsed
  onContinue: () => void
}

export default function UploadProfileCard({ dataset, onContinue }: UploadProfileCardProps) {
  return (
    <div className="mx-auto max-w-xl rounded-xl border border-green-200 bg-green-50 p-6 shadow-sm">
      <h2 className="mb-1 text-base font-semibold text-green-900">{dataset.filename} — profiled</h2>
      <p className="mb-4 text-sm text-green-800">
        {dataset.row_count.toLocaleString()} rows · {dataset.column_count} columns
      </p>

      {dataset.anomalies.length > 0 ? (
        <ul className="mb-4 space-y-1.5">
          {dataset.anomalies.map((a, i) => (
            <li key={i} className="rounded-md bg-white/70 px-3 py-2 text-sm text-amber-800">
              <span className="font-medium">{a.column}</span>: {a.description}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-sm text-green-700">No anomalies detected.</p>
      )}

      <button
        onClick={onContinue}
        className="rounded-lg bg-green-700 px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-green-800"
      >
        Start asking questions →
      </button>
    </div>
  )
}
