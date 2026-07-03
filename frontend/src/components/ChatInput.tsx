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
    <form onSubmit={submit} className="p-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={e => setValue(e.target.value)}
          disabled={disabled}
          placeholder={disabled ? (disabledReason ?? 'Waiting on the current run…') : 'Ask a question about your dataset…'}
          className="flex-1 rounded-full border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none disabled:bg-gray-50 disabled:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500 dark:disabled:bg-gray-800 dark:disabled:text-gray-500"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-full bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50 dark:bg-blue-500 dark:hover:bg-blue-400"
        >
          Ask
        </button>
      </div>
    </form>
  )
}
