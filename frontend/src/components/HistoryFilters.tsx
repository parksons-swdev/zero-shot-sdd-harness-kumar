'use client'

export interface HistoryFilterValues {
  q: string
  dateFrom: string
  dateTo: string
}

interface HistoryFiltersProps {
  values: HistoryFilterValues
  onChange: (next: HistoryFilterValues) => void
  onClear: () => void
}

export default function HistoryFilters({ values, onChange, onClear }: HistoryFiltersProps) {
  const hasActiveFilter =
    values.q.trim() !== '' || values.dateFrom !== '' || values.dateTo !== ''

  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <input
            type="search"
            value={values.q}
            onChange={e => onChange({ ...values, q: e.target.value })}
            placeholder="Search by question text…"
            aria-label="Search by question text"
            data-testid="history-search"
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500 dark:focus:ring-blue-900"
          />
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={values.dateFrom}
            max={values.dateTo || undefined}
            onChange={e => onChange({ ...values, dateFrom: e.target.value })}
            aria-label="Filter runs from date"
            data-testid="history-date-from"
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:[color-scheme:dark] dark:focus:ring-blue-900"
          />
          <span className="text-xs text-gray-400">to</span>
          <input
            type="date"
            value={values.dateTo}
            min={values.dateFrom || undefined}
            onChange={e => onChange({ ...values, dateTo: e.target.value })}
            aria-label="Filter runs to date"
            data-testid="history-date-to"
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:[color-scheme:dark] dark:focus:ring-blue-900"
          />
        </div>
      </div>
      <button
        type="button"
        onClick={onClear}
        disabled={!hasActiveFilter}
        data-testid="history-clear"
        className="shrink-0 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 transition hover:border-gray-400 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-700 dark:text-gray-300 dark:hover:border-gray-500"
      >
        Clear
      </button>
    </div>
  )
}
