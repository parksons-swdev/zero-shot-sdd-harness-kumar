'use client'

import dynamic from 'next/dynamic'
import { useMemo } from 'react'
import type { ChartSpec } from '@/lib/api'
import { useTheme } from '@/components/ThemeProvider'

// react-plotly.js touches `window` at import time, so it must be loaded client-only.
const Plot = dynamic(() => import('react-plotly.js'), { ssr: false })

interface ChartViewProps {
  spec: ChartSpec
}

type PlotlyData = Record<string, unknown>

function toPlotlyTrace(spec: ChartSpec, isDark: boolean): PlotlyData {
  const type = spec.type === 'line' ? 'scatter' : spec.type ?? 'bar'
  const trace: PlotlyData = {
    type,
    x: spec.x,
    y: spec.y,
    marker: { color: isDark ? '#60a5fa' : '#2563eb' },
  }
  if (type === 'scatter') {
    trace.mode = 'lines+markers'
    trace.line = { color: isDark ? '#60a5fa' : '#2563eb' }
  }
  return trace
}

// Theme-aware Plotly layout (Phase 3): a dark template (dark paper/plot
// backgrounds, light font, muted gridlines) in dark mode; a clean light
// template otherwise.
function themedLayout(isDark: boolean): Record<string, unknown> {
  const fontColor = isDark ? '#e5e7eb' : '#111827'
  const gridColor = isDark ? '#374151' : '#e5e7eb'
  const paper = isDark ? '#111827' : '#ffffff'
  const plot = isDark ? '#111827' : '#ffffff'
  return {
    autosize: true,
    margin: { t: 16, r: 16, b: 40, l: 48 },
    dragmode: 'zoom',
    height: 320,
    paper_bgcolor: paper,
    plot_bgcolor: plot,
    font: { color: fontColor },
    xaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
    yaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
  }
}

export default function ChartView({ spec }: ChartViewProps) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const data = useMemo(() => [toPlotlyTrace(spec, isDark)], [spec, isDark])
  const layout = useMemo(() => themedLayout(isDark), [isDark])

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-2 dark:border-gray-800 dark:bg-gray-900" data-testid="chart-view">
      <Plot
        data={data as never}
        layout={layout}
        config={{ scrollZoom: true, displaylogo: false, responsive: true }}
        style={{ width: '100%', height: '320px' }}
        useResizeHandler
      />
    </div>
  )
}
