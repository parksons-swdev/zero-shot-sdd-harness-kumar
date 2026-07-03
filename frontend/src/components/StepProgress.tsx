'use client'

import { useEffect, useState } from 'react'
import { parseServerDate } from '@/lib/dates'

interface StepProgressProps {
  stepCount: number
  totalEstimatedSteps: number
  currentStepLabel?: string
  startedAt?: string
}

// "12.3s" while under a minute; "2m 05s" once a run genuinely runs long —
// a raw fractional-second count (e.g. "19807.0s") is unreadable at any scale.
function formatElapsed(ms: number): string {
  const totalSeconds = ms / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`
}

export default function StepProgress({ stepCount, totalEstimatedSteps, currentStepLabel, startedAt }: StepProgressProps) {
  const [elapsedMs, setElapsedMs] = useState(0)

  useEffect(() => {
    const start = startedAt ? parseServerDate(startedAt).getTime() : Date.now()
    const tick = () => setElapsedMs(Date.now() - start)
    tick()
    const id = setInterval(tick, 200)
    return () => clearInterval(id)
  }, [startedAt])

  const total = Math.max(totalEstimatedSteps, stepCount, 1)
  const pct = Math.min(100, Math.round((stepCount / total) * 100))
  const elapsedLabel = formatElapsed(elapsedMs)

  return (
    <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950" data-testid="step-progress">
      <div className="mb-2 flex items-center justify-between text-sm font-medium text-blue-900 dark:text-blue-200">
        <span>
          Step {stepCount} of {total}
        </span>
        <span className="text-blue-700 dark:text-blue-400">{elapsedLabel} elapsed</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-blue-100 dark:bg-blue-900">
        <div className="h-full rounded-full bg-blue-600 transition-all duration-300 dark:bg-blue-400" style={{ width: `${pct}%` }} />
      </div>
      {currentStepLabel && <p className="mt-2 text-xs text-blue-700 dark:text-blue-400">{currentStepLabel}</p>}
    </div>
  )
}
