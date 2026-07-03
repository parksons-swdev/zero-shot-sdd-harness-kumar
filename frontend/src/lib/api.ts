// Centralized API client for the CSV Insight Agent frontend.
//
// In dev, point NEXT_PUBLIC_API_BASE_URL at the FastAPI server (e.g. http://localhost:8001).
// In production the static export is served BY FastAPI at the same origin under /app,
// so an empty base ("") resolves relative fetches correctly against the same host.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError("Can't reach the server — is it running?", 0, 'network_error')
  }

  let body: unknown
  try {
    body = await res.json()
  } catch {
    body = null
  }

  if (!res.ok) {
    const detail = (body as { detail?: { code?: string; message?: string } } | null)?.detail
    throw new ApiError(detail?.message ?? `Request failed (${res.status})`, res.status, detail?.code)
  }

  const envelope = body as { data: T; error: unknown }
  return envelope.data
}

// ---------- Types (mirrors spec/api.md) ----------

export interface DatasetSchemaColumn {
  name: string
  dtype: string
  null_pct: number
  distinct_count: number
}

export interface DatasetAnomaly {
  column: string
  type: string
  severity: string
  description: string
}

export interface DatasetParsed {
  dataset_id: string
  session_id: string
  status: 'parsed'
  filename: string
  row_count: number
  column_count: number
  schema: DatasetSchemaColumn[]
  anomalies: DatasetAnomaly[]
}

export interface DatasetNeedsDecision {
  dataset_id: string
  status: 'needs_decision'
  issue: string
  choices: string[]
}

export type DatasetUploadResult = DatasetParsed | DatasetNeedsDecision

export interface Message {
  role: 'user' | 'assistant'
  content: string
  run_id: string | null
  created_at: string
}

export interface RunStartResult {
  run_id: string
  status: 'running'
}

export type RunStatus = 'running' | 'completed' | 'needs_clarification' | 'failed'

export interface RunResult {
  run_id: string
  status: RunStatus
  // running
  step_count?: number
  total_estimated_steps?: number
  current_step_label?: string
  started_at?: string
  // completed
  question_text?: string
  answer_text?: string
  key_numbers?: Record<string, number | string>
  chart_spec?: ChartSpec
  table_data?: Record<string, unknown>[]
  generated_code?: string
  assumptions?: string[]
  anomalies?: DatasetAnomaly[]
  retry_count?: number
  token_input_count?: number
  token_output_count?: number
  estimated_cost_usd?: number
  completed_at?: string
  // needs_clarification
  clarification_question?: string
  // failed
  stuck_explanation?: string
}

export interface ChartSpec {
  type: string
  x?: (string | number)[]
  y?: (string | number)[]
  [key: string]: unknown
}

export interface RunSummary {
  run_id: string
  dataset_filename: string
  question_text: string
  status: RunStatus
  estimated_cost_usd: number | null
  created_at: string
}

// ---------- Endpoints ----------

export async function uploadDataset(file: File): Promise<DatasetUploadResult> {
  const form = new FormData()
  form.append('file', file)
  return request<DatasetUploadResult>('/datasets', { method: 'POST', body: form })
}

export async function resolveDecision(datasetId: string, choice: string): Promise<DatasetUploadResult> {
  return request<DatasetUploadResult>(`/datasets/${datasetId}/decisions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ choice }),
  })
}

export async function getDataset(datasetId: string): Promise<DatasetParsed> {
  return request<DatasetParsed>(`/datasets/${datasetId}`)
}

export interface DatasetSummary {
  dataset_id: string
  filename: string
  row_count: number
  created_at: string
}

// GET /datasets — recently uploaded datasets, newest first (Phase 2 reselect flow).
export async function listDatasets(): Promise<DatasetSummary[]> {
  return request<DatasetSummary[]>('/datasets')
}

export interface SessionStartResult {
  session_id: string
  dataset_id: string
}

// POST /sessions — start a fresh session against an already-profiled dataset,
// skipping re-upload / re-profiling.
export async function createSession(datasetId: string): Promise<SessionStartResult> {
  return request<SessionStartResult>('/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_id: datasetId }),
  })
}

export async function postMessage(sessionId: string, content: string): Promise<RunStartResult> {
  return request<RunStartResult>(`/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export async function getMessages(sessionId: string): Promise<Message[]> {
  return request<Message[]>(`/sessions/${sessionId}/messages`)
}

export async function getRun(runId: string): Promise<RunResult> {
  return request<RunResult>(`/runs/${runId}`)
}

export interface ListRunsFilters {
  q?: string
  date_from?: string
  date_to?: string
}

export async function listRuns(
  limit = 20,
  offset = 0,
  filters: ListRunsFilters = {},
): Promise<RunSummary[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  params.set('offset', String(offset))
  if (filters.q && filters.q.trim()) params.set('q', filters.q.trim())
  if (filters.date_from) params.set('date_from', filters.date_from)
  if (filters.date_to) params.set('date_to', filters.date_to)
  return request<RunSummary[]>(`/runs?${params.toString()}`)
}
