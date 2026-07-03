'use client'

import dynamic from 'next/dynamic'
import { useMemo } from 'react'
import type { ChartSpec } from '@/lib/api'

// react-plotly.js touches `window` at import time, so it must be loaded client-only.
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false })

interface ChartViewProps {
  spec: ChartSpec
}

type PlotlyData = Record<string, unknown>

function toPlotlyTrace(spec: ChartSpec): PlotlyData {
  const type = spec.type === 'line' ? 'scatter' : spec.type ?? 'bar'
  const trace: PlotlyData = { type, x: spec.x, y: spec.y }
  if (type === 'scatter') trace.mode = 'lines+markers'
  return trace
}

export default function ChartView({ spec }: ChartViewProps) {
  const data = useMemo(() => [toPlotlyTrace(spec)], [spec])

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-2" data-testid="chart-view">
      <Plot
        data={data as never}
        layout={{
          autosize: true,
          margin: { t: 16, r: 16, b: 40, l: 48 },
          dragmode: 'zoom',
          height: 320,
        }}
        config={{ scrollZoom: true, displaylogo: false, responsive: true }}
        style={{ width: '100%', height: '320px' }}
        useResizeHandler
      />
    </div>
  )
}
