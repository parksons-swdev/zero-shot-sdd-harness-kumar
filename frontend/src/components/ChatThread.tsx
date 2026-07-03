'use client'

import ChatMessage, { ChatTurn } from '@/components/ChatMessage'

interface ChatThreadProps {
  turns: ChatTurn[]
}

export default function ChatThread({ turns }: ChatThreadProps) {
  if (turns.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <p className="text-sm text-gray-400">Ask a question about your dataset to get started.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto py-4" data-testid="chat-thread">
      {turns.map(turn => (
        <ChatMessage key={turn.id} turn={turn} />
      ))}
    </div>
  )
}
