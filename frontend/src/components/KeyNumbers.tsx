'use client'

interface KeyNumbersProps {
  numbers: Record<string, number | string>
}

function formatLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatValue(value: number | string): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  return String(value)
}

export default function KeyNumbers({ numbers }: KeyNumbersProps) {
  const entries = Object.entries(numbers)
  if (entries.length === 0) return null

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="key-numbers">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-800/50">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{formatLabel(key)}</p>
          <p className="text-lg font-semibold text-gray-900 dark:text-gray-100">{formatValue(value)}</p>
        </div>
      ))}
    </div>
  )
}
