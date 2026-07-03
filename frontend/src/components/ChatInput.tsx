'use client'

import { useState } from 'react'

interface ChatInputProps {
  disabled: boolean
  disabledReason?: string
  onSend: (content: string) => void
}

export default function ChatInput({ disabled, disabledReason, onSend }: ChatInputProps) {
  const [value, setValue] = useState('')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  return (
    <form onSubmit={submit} className="border-t border-gray-200 bg-white p-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={e => setValue(e.target.value)}
          disabled={disabled}
          placeholder={disabled ? (disabledReason ?? 'Waiting on the current run…') : 'Ask a question about your dataset…'}
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2.5 text-sm shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Ask
        </button>
      </div>
    </form>
  )
}
