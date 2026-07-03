'use client'

import { useCallback, useRef, useState } from 'react'
import {
  ApiError,
  DatasetParsed,
  DatasetUploadResult,
  resolveDecision,
  uploadDataset,
} from '@/lib/api'

const MAX_UPLOAD_MB = 100

interface UploadAreaProps {
  onParsed: (dataset: DatasetParsed) => void
}

export default function UploadArea({ onParsed }: UploadAreaProps) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [needsDecision, setNeedsDecision] = useState<{ dataset_id: string; issue: string; choices: string[] } | null>(
    null,
  )
  const [resolving, setResolving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (file: File) => {
    setError(null)
    setNeedsDecision(null)

    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Please upload a .csv file.')
      return
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_UPLOAD_MB}MB limit.`)
      return
    }

    setUploading(true)
    try {
      const result: DatasetUploadResult = await uploadDataset(file)
      if (result.status === 'needs_decision') {
        setNeedsDecision({ dataset_id: result.dataset_id, issue: result.issue, choices: result.choices })
      } else {
        onParsed(result)
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Upload failed unexpectedly.'
      setError(message)
    } finally {
      setUploading(false)
    }
  }, [onParsed])

  async function handleDecision(choice: string) {
    if (!needsDecision) return
    setResolving(true)
    setError(null)
    try {
      const result = await resolveDecision(needsDecision.dataset_id, choice)
      if (result.status === 'needs_decision') {
        setNeedsDecision({ dataset_id: result.dataset_id, issue: result.issue, choices: result.choices })
      } else {
        setNeedsDecision(null)
        onParsed(result)
      }
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Could not apply that choice.'
      setError(message)
    } finally {
      setResolving(false)
    }
  }

  function choiceLabel(choice: string): string {
    if (choice === 'skip_bad_lines') return 'Skip the bad rows and continue'
    if (choice === 'reupload') return 'Upload a different file'
    return choice
  }

  if (needsDecision) {
    return (
      <div className="mx-auto max-w-xl rounded-xl border border-amber-200 bg-amber-50 p-6 shadow-sm">
        <h2 className="mb-2 text-base font-semibold text-amber-900">This file needs a decision</h2>
        <p className="mb-4 text-sm text-amber-800">{needsDecision.issue}</p>
        <div className="flex flex-wrap gap-3">
          {needsDecision.choices.map(choice => (
            <button
              key={choice}
              onClick={() => (choice === 'reupload' ? setNeedsDecision(null) : handleDecision(choice))}
              disabled={resolving}
              className="rounded-lg border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-900 shadow-sm hover:bg-amber-100 disabled:opacity-50"
            >
              {resolving ? 'Working…' : choiceLabel(choice)}
            </button>
          ))}
        </div>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-xl">
      <div
        onDragOver={e => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files?.[0]
          if (file) handleFile(file)
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-12 text-center transition-colors ${
          dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={e => {
            const file = e.target.files?.[0]
            if (file) handleFile(file)
          }}
        />
        {uploading ? (
          <>
            <div className="mb-3 h-8 w-8 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600" />
            <p className="text-sm font-medium text-gray-700">Uploading and profiling…</p>
          </>
        ) : (
          <>
            <p className="mb-1 text-sm font-medium text-gray-700">Drag &amp; drop a CSV here, or click to browse</p>
            <p className="text-xs text-gray-400">Up to {MAX_UPLOAD_MB}MB · .csv only</p>
          </>
        )}
      </div>
      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}
    </div>
  )
}
