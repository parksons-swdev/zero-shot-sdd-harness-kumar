'use client'

import dynamic from 'next/dynamic'
import { useEffect, useState } from 'react'
import { useTheme } from '@/components/ThemeProvider'

// react-plotly.js touches `window` at import time — must never be evaluated
// during Next's static export build, only in the browser.
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false })

interface ChartSpec {
  type?: string
  x?: (string | number)[]
  y?: (string | number)[]
  [key: string]: unknown
}

interface RunDetail {
  run_id: string
  status: 'running' | 'completed' | 'needs_clarification' | 'failed' | string
  question_text?: string
  answer_text?: string
  key_numbers?: Record<string, string | number>
  chart_spec?: ChartSpec
  table_data?: Record<string, unknown>[]
  generated_code?: string
  assumptions?: string[]
  anomalies?: { column: string; type: string; severity: string; description: string }[]
  retry_count?: number
  step_count?: number
  total_estimated_steps?: number
  current_step_label?: string
  token_input_count?: number
  token_output_count?: number
  estimated_cost_usd?: number
  clarification_question?: string
  stuck_explanation?: string
  started_at?: string
  completed_at?: string
}

function TableView({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No table data for this run.</p>
  }
  const columns = Object.keys(rows[0])
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
      <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
        <thead className="bg-gray-50 dark:bg-gray-800/50">
          <tr>
            {columns.map(col => (
              <th key={col} className="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-300">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map(col => (
                <td key={col} className="px-3 py-2 text-gray-800 dark:text-gray-300">
                  {String(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ChartView({ spec, isDark }: { spec: ChartSpec; isDark: boolean }) {
  if (!spec || !spec.x || !spec.y) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No chart data for this run.</p>
  }
  const chartType = spec.type === 'line' ? 'scatter' : (spec.type ?? 'bar')
  const gridColor = isDark ? '#374151' : '#e5e7eb'
  return (
    <div className="rounded-lg border border-gray-200 p-2 dark:border-gray-800 dark:bg-gray-900" data-testid="history-chart">
      <Plot
        data={[
          {
            x: spec.x,
            y: spec.y,
            type: chartType as 'bar' | 'scatter',
            mode: chartType === 'scatter' ? 'lines+markers' : undefined,
            marker: { color: isDark ? '#60a5fa' : '#2563eb' },
          },
        ]}
        layout={{
          autosize: true,
          margin: { t: 20, r: 20, b: 40, l: 50 },
          height: 360,
          paper_bgcolor: isDark ? '#111827' : '#ffffff',
          plot_bgcolor: isDark ? '#111827' : '#ffffff',
          font: { color: isDark ? '#e5e7eb' : '#111827' },
          xaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
          yaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
        }}
        useResizeHandler
        style={{ width: '100%' }}
        config={{ displaylogo: false }}
      />
    </div>
  )
}

export default function HistoryDetail({ runId, onBack }: { runId: string; onBack: () => void }) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [codeOpen, setCodeOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`/runs/${runId}`)
        const body = await res.json()
        if (!res.ok) {
          throw new Error(body?.detail?.message ?? `Request failed (${res.status})`)
        }
        if (!cancelled) setDetail(body.data)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Can't reach the server — is it running?")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [runId])

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
      >
        ← Back to history
      </button>

      {loading && (
        <div className="space-y-3" data-testid="history-detail-loading">
          <div className="h-6 w-2/3 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
          <div className="h-24 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
          <div className="h-64 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</div>
      )}

      {!loading && !error && detail && (
        <div className="space-y-6" data-testid="history-detail">
          {detail.question_text && (
            <div>
              <p className="text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">Question</p>
              <p className="text-base font-medium text-gray-900 dark:text-gray-100">{detail.question_text}</p>
            </div>
          )}

          {detail.status === 'needs_clarification' && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              This run ended with a clarifying question: {detail.clarification_question}
            </div>
          )}

          {detail.status === 'running' && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300">
              This run was still in progress when last recorded (
              {detail.current_step_label ?? 'processing'}
              ).
            </div>
          )}

          {detail.status === 'failed' && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
              <p className="font-medium">This run got stuck:</p>
              <p className="mt-1 whitespace-pre-wrap">{detail.stuck_explanation}</p>
            </div>
          )}

          {detail.status === 'completed' && (
            <>
              {detail.answer_text && (
                <div>
                  <p className="text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">Answer</p>
                  <p className="whitespace-pre-wrap text-sm text-gray-800 dark:text-gray-200">{detail.answer_text}</p>
                </div>
              )}

              {detail.key_numbers && Object.keys(detail.key_numbers).length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">Key numbers</p>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(detail.key_numbers).map(([label, value]) => (
                      <div key={label} className="rounded-lg border border-gray-200 bg-white px-4 py-2 shadow-sm dark:border-gray-800 dark:bg-gray-900">
                        <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
                        <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{String(value)}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {detail.chart_spec && (
                <div>
                  <p className="mb-2 text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">Chart</p>
                  <ChartView spec={detail.chart_spec} isDark={isDark} />
                </div>
              )}

              {detail.table_data && (
                <div>
                  <p className="mb-2 text-xs font-medium tracking-wide text-gray-400 uppercase dark:text-gray-500">Table</p>
                  <TableView rows={detail.table_data} />
                </div>
              )}

              {detail.assumptions && detail.assumptions.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                  {detail.assumptions.map((a, i) => (
                    <p key={i}>Note: {a}</p>
                  ))}
                </div>
              )}

              {detail.anomalies && detail.anomalies.length > 0 && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700 dark:border-gray-800 dark:bg-gray-800/50 dark:text-gray-300">
                  <p className="mb-1 font-medium">Anomalies noted at analysis time</p>
                  <ul className="list-inside list-disc space-y-0.5">
                    {detail.anomalies.map((a, i) => (
                      <li key={i}>{a.description}</li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.generated_code && (
                <div>
                  <button
                    type="button"
                    onClick={() => setCodeOpen(o => !o)}
                    className="text-sm font-medium text-blue-700 hover:underline dark:text-blue-400"
                  >
                    {codeOpen ? 'Hide analysis code' : 'View analysis code'}
                  </button>
                  {codeOpen && (
                    <pre className="mt-2 overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100 dark:bg-black">
                      <code>{detail.generated_code}</code>
                    </pre>
                  )}
                </div>
              )}

              <p className="text-xs text-gray-400 dark:text-gray-500">
                ~{(detail.token_input_count ?? 0) + (detail.token_output_count ?? 0)} tokens · $
                {(detail.estimated_cost_usd ?? 0).toFixed(4)}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
