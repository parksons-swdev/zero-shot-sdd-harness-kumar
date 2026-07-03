'use client'

import { useState } from 'react'

interface CodeViewProps {
  code: string
}

export default function CodeView({ code }: CodeViewProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-3 border-t border-gray-100 pt-3 dark:border-gray-800">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      >
        <span className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}>&#9656;</span>
        View analysis code
      </button>
      {open && (
        <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-gray-900 p-3 text-xs text-gray-100 dark:bg-black">
          <code className="font-mono">{code}</code>
        </pre>
      )}
    </div>
  )
}
