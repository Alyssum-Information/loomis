/**
 * Typed client for the Loomis backend API.
 *
 * Same-origin "/api/v1" paths: proxied to the backend in dev (see vite.config.mts),
 * served by the backend itself in production. Field names mirror the backend models
 * (snake_case). Contract: ../../docs/11-api-specification.md
 *
 * Hand-written for now; the backend publishes an OpenAPI schema this can be
 * generated from later.
 */

const BASE = '/api/v1'

// --- types (mirror backend models / schemas) ---

export interface Health {
  status: string
  version: string
  db_version: number | null
}

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export type DeviceKind = 'usb' | 'folder'

export interface Device {
  id: string
  name: string
  kind: DeviceKind
  source_path?: string | null
  volume_serial?: string | null
  owner_speaker_id?: number | null
  auto_delete: boolean
  transcode_policy: string
  registered: boolean
  registered_at?: string | null
  last_seen_at?: string | null
}

export interface Recording {
  id: string
  device_id: string
  library_path?: string | null
  sha256: string
  size_bytes: number
  duration_s?: number | null
  codec?: string | null
  recorded_at?: string | null
  imported_at?: string | null
  status: string
  kind?: string | null
}

export interface Transcript {
  id: string
  recording_id: string
  engine: string
  model?: string | null
  language?: string | null
  text?: string | null
}

export interface Segment {
  id?: number | null
  transcript_id: string
  idx: number
  start_s: number
  end_s: number
  speaker_id?: number | null
  diarization_label?: string | null
  text?: string | null
}

export interface TranscriptDetail {
  transcript: Transcript
  segments: Segment[]
}

export interface TimelineDay {
  date: string
  has_diary: boolean
  meeting_count: number
}

export interface DiaryEntry {
  id: string
  date: string
  title?: string | null
  metadata: Record<string, unknown>
  model?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface Meeting {
  id: string
  title?: string | null
  occurred_on?: string | null
  metadata: Record<string, unknown>
  model?: string | null
}

export interface Speaker {
  id: number
  display_name?: string | null
  /** LLM-proposed name (FR-5.8); becomes the display name only when the user accepts it. */
  suggested_name?: string | null
  is_provisional: boolean
  needs_review: boolean
}

export interface Job {
  id: number
  type: string
  payload: Record<string, unknown>
  status: string
  attempts: number
  last_error?: string | null
  updated_at?: string | null
}

export interface SearchHit {
  ref_kind: string
  ref_id: string
  title: string
  snippet: string
}

export type StageState = 'pending' | 'active' | 'done' | 'failed'

export interface PipelineStage {
  state: StageState
  job_id?: number | null
  error?: string | null
}

export interface RecordPipeline {
  recording_id: string
  name: string
  device_id: string
  device_name?: string | null
  kind?: string | null
  status: string
  recorded_at?: string | null
  imported_at?: string | null
  duration_s?: number | null
  size_bytes: number
  backup: PipelineStage
  stt: PipelineStage
  summary: PipelineStage
  updated_at?: string | null
}

export interface PendingDevice {
  volume: string
  registered: boolean
}

export interface JobAccepted {
  job_id: number
}

// --- fetch helpers ---

type Params = Record<string, string | number | undefined | null>

function query (params?: Params): string {
  if (!params) {
    return ''
  }
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

async function parseError (res: Response): Promise<never> {
  let message = `HTTP ${res.status}`
  try {
    const body = await res.json() as { error?: { message?: string } }
    if (body.error?.message) {
      message = body.error.message
    }
  } catch { /* non-JSON error body */ }
  throw new Error(message)
}

async function getJson<T> (path: string, params?: Params): Promise<T> {
  const res = await fetch(`${BASE}${path}${query(params)}`)
  if (!res.ok) {
    await parseError(res)
  }
  return await res.json() as T
}

async function sendJson<T> (method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    await parseError(res)
  }
  return await res.json() as T
}

async function sendNoContent (method: string, path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method })
  if (!res.ok) {
    await parseError(res)
  }
}

// --- endpoints ---

export const getHealth = (): Promise<Health> => getJson<Health>('/health')

export const listDevices = (): Promise<Device[]> => getJson<Device[]>('/devices')

export function getRecordings (params?: { limit?: number, cursor?: string, device_id?: string, status?: string, date?: string }): Promise<Page<Recording>> {
  return getJson<Page<Recording>>('/recordings', params)
}

export function getRecording (id: string): Promise<Recording> {
  return getJson<Recording>(`/recordings/${id}`)
}

export function getTranscript (id: string): Promise<TranscriptDetail> {
  return getJson<TranscriptDetail>(`/recordings/${id}/transcript`)
}

export const audioUrl = (id: string): string => `${BASE}/recordings/${id}/audio`

export function getTimeline (params?: { from?: string, to?: string }): Promise<TimelineDay[]> {
  return getJson<TimelineDay[]>('/timeline', params)
}

export function getDiary (date: string): Promise<DiaryEntry> {
  return getJson<DiaryEntry>(`/diary/${date}`)
}

export const getMeeting = (id: string): Promise<Meeting> => getJson<Meeting>(`/meetings/${id}`)

export const listSpeakers = (): Promise<Speaker[]> => getJson<Speaker[]>('/speakers')

export function search (q: string, limit = 50): Promise<SearchHit[]> {
  return getJson<SearchHit[]>('/search', { q, limit })
}

export function listJobs (params?: { status?: string, limit?: number }): Promise<Job[]> {
  return getJson<Job[]>('/jobs', params)
}

export function getRecords (params?: { limit?: number, cursor?: string }): Promise<Page<RecordPipeline>> {
  return getJson<Page<RecordPipeline>>('/pipeline', params)
}

// --- commands (writes) ---

export function getPendingDevices (): Promise<PendingDevice[]> {
  return getJson<PendingDevice[]>('/devices/pending')
}

export function registerDevice (
  body: { volume: string, name?: string, auto_delete?: boolean, kind?: DeviceKind },
): Promise<Device> {
  return sendJson<Device>('POST', '/devices/register', body)
}

export function updateDevice (
  id: string,
  body: {
    name?: string
    auto_delete?: boolean
    transcode_policy?: string
    min_free_bytes?: number
  },
): Promise<Device> {
  return sendJson<Device>('PATCH', `/devices/${id}`, body)
}

export function unregisterDevice (id: string): Promise<void> {
  return sendNoContent('DELETE', `/devices/${id}`)
}

export function updateSpeaker (
  id: number,
  body: { display_name?: string, is_provisional?: boolean },
): Promise<Speaker> {
  return sendJson<Speaker>('PATCH', `/speakers/${id}`, body)
}

export function mergeSpeakers (sourceId: number, targetId: number): Promise<JobAccepted> {
  return sendJson<JobAccepted>('POST', '/speakers/merge', { source_id: sourceId, target_id: targetId })
}

export function splitSpeaker (id: number, recordingId: string): Promise<JobAccepted> {
  return sendJson<JobAccepted>('POST', `/speakers/${id}/split`, { recording_id: recordingId })
}

// --- cloud sync (FR-8) ---

export interface CloudRemote {
  name: string
  scope: string[]
  direction: string
  dest: string
}

export interface CloudStatus {
  enabled: boolean
  rclone_available: boolean
  remotes: CloudRemote[]
}

export interface CloudSyncEntry {
  id: number
  remote: string
  scope: string[]
  started_at?: string | null
  finished_at?: string | null
  result?: string | null
  stats: Record<string, unknown>
}

export const getCloudStatus = (): Promise<CloudStatus> => getJson<CloudStatus>('/cloud/remotes')

export function syncCloud (remote?: string): Promise<JobAccepted> {
  return sendJson<JobAccepted>('POST', '/cloud/sync', remote ? { remote } : {})
}

export function getCloudLog (limit = 20): Promise<CloudSyncEntry[]> {
  return getJson<CloudSyncEntry[]>('/cloud/log', { limit })
}

export function retranscribeRecording (id: string): Promise<JobAccepted> {
  return sendJson<JobAccepted>('POST', `/recordings/${id}/retranscribe`)
}

/** Bulk re-transcription; e.g. { not_language: 'zh' } re-runs every misdetected file. */
export function retranscribeAll (
  body: { language?: string, not_language?: string } = {},
): Promise<{ requeued: number }> {
  return sendJson<{ requeued: number }>('POST', '/recordings/retranscribe', body)
}

export function retryJob (id: number): Promise<JobAccepted> {
  return sendJson<JobAccepted>('POST', `/jobs/${id}/retry`)
}

export function retryAllJobs (): Promise<{ requeued: number }> {
  return sendJson<{ requeued: number }>('POST', '/jobs/retry-all')
}
