'use client'

import { useEffect, useState } from 'react'

interface StepProgressProps {
  stepCount: number
  totalEstimatedSteps: number
  currentStepLabel?: string
  startedAt?: string
}

export default function StepProgress({ stepCount, totalEstimatedSteps, currentStepLabel, startedAt }: StepProgressProps) {
  const [elapsedMs, setElapsedMs] = useState(0)

  useEffect(() => {
    const start = startedAt ? new Date(startedAt).getTime() : Date.now()
    const tick = () => setElapsedMs(Date.now() - start)
    tick()
    const id = setInterval(tick, 200)
    return () => clearInterval(id)
  }, [startedAt])

  const total = Math.max(totalEstimatedSteps, stepCount, 1)
  const pct = Math.min(100, Math.round((stepCount / total) * 100))
  const elapsedSeconds = (elapsedMs / 1000).toFixed(1)

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4" data-testid="step-progress">
      <div className="mb-2 flex items-center justify-between text-sm font-medium text-blue-900">
        <span>
          Step {stepCount} of {total}
        </span>
        <span className="text-blue-700">{elapsedSeconds}s elapsed</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-blue-100">
        <div className="h-full rounded-full bg-blue-600 transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      {currentStepLabel && <p className="mt-2 text-xs text-blue-700">{currentStepLabel}</p>}
    </div>
  )
}
