'use client'

import { useMemo, useState } from 'react'

interface SummaryTableProps {
  rows: Record<string, unknown>[]
}

type SortDir = 'asc' | 'desc'

export default function SummaryTable({ rows }: SummaryTableProps) {
  const columns = useMemo(() => (rows.length > 0 ? Object.keys(rows[0]) : []), [rows])
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const sortedRows = useMemo(() => {
    if (!sortCol) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = a[sortCol]
      const bv = b[sortCol]
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av
      return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
    })
    return copy
  }, [rows, sortCol, sortDir])

  function toggleSort(col: string) {
    if (sortCol === col) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }

  if (rows.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">No table data for this answer.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800" data-testid="summary-table">
      <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-800">
        <thead className="bg-gray-50 dark:bg-gray-800/50">
          <tr>
            {columns.map(col => (
              <th
                key={col}
                onClick={() => toggleSort(col)}
                className="cursor-pointer select-none px-3 py-2 text-left text-xs font-medium tracking-wide text-gray-500 uppercase hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {col}
                {sortCol === col && <span className="ml-1">{sortDir === 'asc' ? '▲' : '▼'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
          {sortedRows.map((row, i) => (
            <tr key={i}>
              {columns.map(col => (
                <td key={col} className="px-3 py-2 text-gray-700 dark:text-gray-300">
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
