'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import UploadArea from '@/components/UploadArea'
import UploadProfileCard from '@/components/UploadProfileCard'
import ChatThread from '@/components/ChatThread'
import ChatInput from '@/components/ChatInput'
import { ChatTurn } from '@/components/ChatMessage'
import { ApiError, DatasetParsed, getMessages, getRun, postMessage, RunResult } from '@/lib/api'
import { RESELECT_STORAGE_KEY } from '@/components/DatasetPicker'

const POLL_INTERVAL_MS = 750

export default function Home() {
  const [dataset, setDataset] = useState<DatasetParsed | null>(null)
  const [showProfile, setShowProfile] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [networkError, setNetworkError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const isRunInFlight = activeRunId !== null

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const applyRunResult = useCallback((runId: string, run: RunResult) => {
    setTurns(prev => {
      const next = [...prev]
      const idx = next.findIndex(t => t.id === `run-${runId}`)
      const turn: ChatTurn = { id: `run-${runId}`, role: 'assistant', createdAt: new Date().toISOString(), run }
      if (idx >= 0) next[idx] = turn
      else next.push(turn)
      return next
    })
  }, [])

  const pollRun = useCallback(
    (runId: string) => {
      stopPolling()
      pollRef.current = setInterval(async () => {
        try {
          const run = await getRun(runId)
          applyRunResult(runId, run)
          setNetworkError(null)
          if (run.status !== 'running') {
            stopPolling()
            setActiveRunId(null)
          }
        } catch (e) {
          if (e instanceof ApiError && e.code === 'network_error') {
            setNetworkError(e.message)
          }
        }
      }, POLL_INTERVAL_MS)
    },
    [applyRunResult, stopPolling],
  )

  useEffect(() => stopPolling, [stopPolling])

  // Reselect flow (Phase 2 "Recent Datasets"): when the user reopens a dataset
  // from /datasets, its profile + freshly-created session_id are handed over via
  // sessionStorage. Hydrate straight into the chat workspace, skipping the
  // upload/profile screens, and load any prior conversation for the new session.
  useEffect(() => {
    let raw: string | null = null
    try {
      raw = sessionStorage.getItem(RESELECT_STORAGE_KEY)
    } catch {
      raw = null
    }
    if (!raw) return
    try {
      sessionStorage.removeItem(RESELECT_STORAGE_KEY)
    } catch {
      // ignore
    }
    let reselected: DatasetParsed | null = null
    try {
      reselected = JSON.parse(raw) as DatasetParsed
    } catch {
      reselected = null
    }
    if (!reselected || !reselected.session_id) return

    setDataset(reselected)
    setShowProfile(false)
    ;(async () => {
      try {
        const history = await getMessages(reselected.session_id)
        const historyTurns: ChatTurn[] = []
        for (const m of history) {
          if (m.role === 'user') {
            historyTurns.push({ id: `msg-${m.created_at}-${m.content}`, role: 'user', createdAt: m.created_at, content: m.content })
          } else if (m.run_id) {
            try {
              const run = await getRun(m.run_id)
              historyTurns.push({ id: `run-${m.run_id}`, role: 'assistant', createdAt: m.created_at, run })
            } catch {
              historyTurns.push({
                id: `run-${m.run_id}`,
                role: 'assistant',
                createdAt: m.created_at,
                run: { run_id: m.run_id, status: 'completed', answer_text: m.content },
              })
            }
          }
        }
        setTurns(historyTurns)
      } catch {
        // Fresh session (no prior history) or backend unreachable — start empty.
        setTurns([])
      }
    })()
  }, [])

  const handleParsed = useCallback((parsed: DatasetParsed) => {
    setDataset(parsed)
    setShowProfile(true)
  }, [])

  const handleContinue = useCallback(async () => {
    if (!dataset) return
    setShowProfile(false)
    try {
      const history = await getMessages(dataset.session_id)
      const historyTurns: ChatTurn[] = []
      for (const m of history) {
        if (m.role === 'user') {
          historyTurns.push({ id: `msg-${m.created_at}-${m.content}`, role: 'user', createdAt: m.created_at, content: m.content })
        } else if (m.run_id) {
          try {
            const run = await getRun(m.run_id)
            historyTurns.push({ id: `run-${m.run_id}`, role: 'assistant', createdAt: m.created_at, run })
          } catch {
            historyTurns.push({
              id: `run-${m.run_id}`,
              role: 'assistant',
              createdAt: m.created_at,
              run: { run_id: m.run_id, status: 'completed', answer_text: m.content },
            })
          }
        }
      }
      setTurns(historyTurns)
    } catch {
      // No prior history yet, or backend not reachable — start with an empty thread.
      setTurns([])
    }
  }, [dataset])

  const handleSend = useCallback(
    async (content: string) => {
      if (!dataset) return
      const userTurn: ChatTurn = { id: `user-${Date.now()}`, role: 'user', createdAt: new Date().toISOString(), content }
      setTurns(prev => [...prev, userTurn])
      setNetworkError(null)
      try {
        const started = await postMessage(dataset.session_id, content)
        const runningTurn: ChatTurn = {
          id: `run-${started.run_id}`,
          role: 'assistant',
          createdAt: new Date().toISOString(),
          run: { run_id: started.run_id, status: 'running', step_count: 0, total_estimated_steps: 5 },
        }
        setTurns(prev => [...prev, runningTurn])
        setActiveRunId(started.run_id)
        pollRun(started.run_id)
      } catch (e) {
        const message = e instanceof ApiError ? e.message : 'Could not send that question.'
        if (e instanceof ApiError && e.code === 'network_error') setNetworkError(message)
        setTurns(prev => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            role: 'assistant',
            createdAt: new Date().toISOString(),
            run: { run_id: 'error', status: 'failed', stuck_explanation: message },
          },
        ])
      }
    },
    [dataset, pollRun],
  )

  if (dataset && showProfile) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <UploadProfileCard dataset={dataset} onContinue={handleContinue} />
      </div>
    )
  }

  if (!dataset) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <h1 className="mb-2 text-center text-2xl font-bold tracking-tight text-gray-900">CSV Insight Agent</h1>
        <p className="mb-8 text-center text-sm text-gray-500">Upload a CSV to start asking questions about it.</p>
        <UploadArea onParsed={handleParsed} />
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-4rem)] max-w-3xl flex-col px-4">
      <div className="border-b border-gray-200 py-3">
        <p className="text-sm font-medium text-gray-700">{dataset.filename}</p>
        <p className="text-xs text-gray-400">
          {dataset.row_count.toLocaleString()} rows · {dataset.column_count} columns
        </p>
      </div>

      {networkError && (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          <span>{networkError}</span>
          <button onClick={() => setNetworkError(null)} className="ml-4 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      <ChatThread turns={turns} />

      <ChatInput
        disabled={isRunInFlight || !!networkError}
        disabledReason={isRunInFlight ? 'Waiting for the current answer…' : "Can't reach the server…"}
        onSend={handleSend}
      />
    </div>
  )
}
