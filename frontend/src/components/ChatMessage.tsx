'use client'

import { RunResult } from '@/lib/api'
import ChartView from '@/components/ChartView'
import CodeView from '@/components/CodeView'
import KeyNumbers from '@/components/KeyNumbers'
import StepProgress from '@/components/StepProgress'
import SummaryTable from '@/components/SummaryTable'

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  createdAt: string
  content?: string // plain user text, or fallback assistant text before run resolves
  run?: RunResult // present for assistant turns backed by a run
}

interface ChatMessageProps {
  turn: ChatTurn
}

function CostBadge({ run }: { run: RunResult }) {
  const tokens = (run.token_input_count ?? 0) + (run.token_output_count ?? 0)
  if (tokens === 0 && !run.estimated_cost_usd) return null
  return (
    <div className="mt-3 inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-500">
      ~{tokens.toLocaleString()} tokens · ${run.estimated_cost_usd?.toFixed(4) ?? '0.0000'}
    </div>
  )
}

function AssumptionBanner({ assumptions }: { assumptions: string[] }) {
  if (!assumptions || assumptions.length === 0) return null
  return (
    <div className="mt-3 space-y-1.5">
      {assumptions.map((a, i) => (
        <div key={i} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
          Note: I assumed {a}.
        </div>
      ))}
    </div>
  )
}

function AnomalyBanner({ anomalies }: { anomalies: RunResult['anomalies'] }) {
  if (!anomalies || anomalies.length === 0) return null
  return (
    <div className="mt-3 space-y-1.5">
      {anomalies.map((a, i) => (
        <div key={i} className="rounded-md border border-orange-200 bg-orange-50 px-3 py-1.5 text-xs text-orange-800">
          Data quality: {a.column} — {a.description}
        </div>
      ))}
    </div>
  )
}

function AssistantBubble({ turn }: { turn: ChatTurn }) {
  const run = turn.run

  if (!run || run.status === 'running') {
    return (
      <StepProgress
        stepCount={run?.step_count ?? 0}
        totalEstimatedSteps={run?.total_estimated_steps ?? 5}
        currentStepLabel={run?.current_step_label}
        startedAt={run?.started_at}
      />
    )
  }

  if (run.status === 'needs_clarification') {
    return (
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4" data-testid="clarification-turn">
        <p className="mb-1 text-xs font-semibold tracking-wide text-indigo-500 uppercase">Clarifying question</p>
        <p className="text-sm text-indigo-900">{run.clarification_question}</p>
      </div>
    )
  }

  if (run.status === 'failed') {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4" data-testid="stuck-turn">
        <p className="mb-1 text-xs font-semibold tracking-wide text-red-500 uppercase">I got stuck</p>
        <p className="text-sm whitespace-pre-wrap text-red-900">{run.stuck_explanation}</p>
        {run.generated_code && <CodeView code={run.generated_code} />}
      </div>
    )
  }

  // completed
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm" data-testid="completed-turn">
      <p className="text-sm whitespace-pre-wrap text-gray-800">{run.answer_text}</p>

      <AssumptionBanner assumptions={run.assumptions ?? []} />
      <AnomalyBanner anomalies={run.anomalies} />

      {run.key_numbers && Object.keys(run.key_numbers).length > 0 && (
        <div className="mt-4">
          <KeyNumbers numbers={run.key_numbers} />
        </div>
      )}

      {run.chart_spec && (
        <div className="mt-4">
          <ChartView spec={run.chart_spec} />
        </div>
      )}

      {run.table_data && (
        <div className="mt-4">
          <SummaryTable rows={run.table_data} />
        </div>
      )}

      {run.generated_code && <CodeView code={run.generated_code} />}

      <CostBadge run={run} />
    </div>
  )
}

export default function ChatMessage({ turn }: ChatMessageProps) {
  if (turn.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-xl bg-blue-600 px-4 py-2.5 text-sm text-white shadow-sm">
          {turn.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-2xl">
        <AssistantBubble turn={turn} />
      </div>
    </div>
  )
}
