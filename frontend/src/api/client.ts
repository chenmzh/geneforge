/**
 * Thin typed fetch wrapper: injects the bearer token, refreshes it once on 401,
 * and normalises the backend's `{code, message, detail}` error envelope.
 */
import type {
  AlignResult, AuditEntry, Capabilities, DashboardSummary, DigestResult, EditOp, EnzymeInfo,
  EnzymeScanResult, ExternalResource, Feature, ImportResult, Job, MsaResult, Orf, Page, PcrResult,
  PrimerPair, PrimerStats, Project, SequenceDetail, SequenceStats, SequenceSummary, SequenceVersion,
  StoredPrimer, Token, User,
} from './types'

const BASE = '/api/v1'
const TOKEN_KEY = 'geneforge.tokens'

export interface Tokens { access: string; refresh: string }

export class ApiError extends Error {
  status: number
  code: string
  detail?: unknown
  constructor(status: number, code: string, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export function loadTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY)
    return raw ? (JSON.parse(raw) as Tokens) : null
  } catch {
    return null
  }
}

export function saveTokens(tokens: Tokens | null) {
  if (tokens) localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens))
  else localStorage.removeItem(TOKEN_KEY)
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const current = loadTokens()
  if (!current?.refresh) return false
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: current.refresh }),
    })
      .then(async (res) => {
        if (!res.ok) {
          saveTokens(null)
          return false
        }
        const data = (await res.json()) as Token
        saveTokens({ access: data.access_token, refresh: data.refresh_token })
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

interface RequestOptions {
  method?: string
  body?: unknown
  raw?: boolean
  formData?: FormData
  retry?: boolean
  signal?: AbortSignal
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const tokens = loadTokens()
  const headers: Record<string, string> = {}
  if (tokens?.access) headers.Authorization = `Bearer ${tokens.access}`
  let body: BodyInit | undefined
  if (opts.formData) {
    body = opts.formData
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }

  const res = await fetch(`${BASE}${path}`, {
    method: opts.method || (body ? 'POST' : 'GET'),
    headers,
    body,
    signal: opts.signal,
  })

  if (res.status === 401 && opts.retry !== false && tokens?.refresh) {
    if (await refreshTokens()) return request<T>(path, { ...opts, retry: false })
  }

  if (!res.ok) {
    let code = 'error'
    let message = `${res.status} ${res.statusText}`
    let detail: unknown
    try {
      const payload = await res.json()
      code = payload.code ?? code
      message = payload.message ?? message
      detail = payload.detail
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) saveTokens(null)
    throw new ApiError(res.status, code, message, detail)
  }

  if (opts.raw) return (await res.text()) as unknown as T
  if (res.status === 204) return undefined as unknown as T
  return (await res.json()) as T
}

/* ------------------------------------------------------------------ api --- */
export const api = {
  // auth
  login: (username: string, password: string) =>
    request<Token>('/auth/login', { body: { username, password } }),
  register: (payload: { email: string; username: string; password: string; full_name?: string }) =>
    request<User>('/auth/register', { body: payload }),
  me: () => request<User>('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    request<void>('/auth/change-password', { body: { current_password, new_password } }),
  apiKeys: () => request<{ id: string; name: string; prefix: string; is_active: boolean; created_at: string }[]>('/auth/api-keys'),
  createApiKey: (name: string, expires_in_days?: number) =>
    request<{ id: string; key: string; name: string }>('/auth/api-keys', { body: { name, expires_in_days } }),
  revokeApiKey: (id: string) => request<void>(`/auth/api-keys/${id}`, { method: 'DELETE' }),

  // system
  capabilities: () => request<Capabilities>('/capabilities'),
  summary: () => request<DashboardSummary>('/me/summary'),
  instanceStats: () => request<Record<string, unknown>>('/stats'),
  auditLogs: (size = 100) => request<Page<AuditEntry>>(`/audit-logs?size=${size}`),

  // users (admin)
  users: (search = '') => request<Page<User>>(`/users?search=${encodeURIComponent(search)}`),
  createUser: (payload: { email: string; username: string; password: string; role?: string; full_name?: string }) =>
    request<User>('/users', { body: payload }),
  updateUser: (id: string, payload: Record<string, unknown>) =>
    request<User>(`/users/${id}`, { method: 'PATCH', body: payload }),

  // projects
  projects: (search = '') => request<Page<Project>>(`/projects?search=${encodeURIComponent(search)}`),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: { name: string; description?: string; tags?: string[] }) =>
    request<Project>('/projects', { body: payload }),
  updateProject: (id: string, payload: Record<string, unknown>) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body: payload }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),
  addMember: (id: string, payload: { username?: string; email?: string; role: string }) =>
    request<{ id: string; user_id: string; role: string }>(`/projects/${id}/members`, { body: payload }),
  removeMember: (id: string, userId: string) =>
    request<void>(`/projects/${id}/members/${userId}`, { method: 'DELETE' }),

  // sequences
  sequences: (projectId: string, search = '') =>
    request<Page<SequenceSummary>>(`/projects/${projectId}/sequences?search=${encodeURIComponent(search)}&size=200`),
  sequence: (id: string) => request<SequenceDetail>(`/sequences/${id}`),
  createSequence: (projectId: string, payload: Record<string, unknown>) =>
    request<SequenceDetail>(`/projects/${projectId}/sequences`, { body: payload }),
  updateSequence: (id: string, payload: Record<string, unknown>) =>
    request<SequenceDetail>(`/sequences/${id}`, { method: 'PATCH', body: payload }),
  deleteSequence: (id: string) => request<void>(`/sequences/${id}`, { method: 'DELETE' }),
  copySequence: (id: string, newName?: string) =>
    request<SequenceDetail>(`/sequences/${id}/copy${newName ? `?new_name=${encodeURIComponent(newName)}` : ''}`, { method: 'POST' }),
  editSequence: (id: string, operations: EditOp[], message?: string) =>
    request<SequenceDetail>(`/sequences/${id}/edit`, { body: { operations, message } }),
  versions: (id: string) => request<SequenceVersion[]>(`/sequences/${id}/versions`),
  restoreVersion: (id: string, version: number) =>
    request<SequenceDetail>(`/sequences/${id}/versions/${version}/restore`, { method: 'POST' }),
  stats: (id: string) => request<SequenceStats>(`/sequences/${id}/stats`),
  exportSequence: (id: string, format: string) =>
    request<string>(`/sequences/${id}/export?format=${format}&download=false`, { raw: true }),
  autoAnnotate: (id: string, replace: boolean, minOrfAa = 80) =>
    request<SequenceDetail>(`/sequences/${id}/auto-annotate?replace=${replace}&min_orf_aa=${minOrfAa}`, { method: 'POST' }),

  // features
  addFeature: (sequenceId: string, payload: Record<string, unknown>) =>
    request<Feature>(`/sequences/${sequenceId}/features`, { body: payload }),
  updateFeature: (sequenceId: string, featureId: string, payload: Record<string, unknown>) =>
    request<Feature>(`/sequences/${sequenceId}/features/${featureId}`, { method: 'PATCH', body: payload }),
  deleteFeature: (sequenceId: string, featureId: string) =>
    request<void>(`/sequences/${sequenceId}/features/${featureId}`, { method: 'DELETE' }),

  // import
  importFile: (projectId: string, file: File, autoAnnotate = false) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<ImportResult>(
      `/projects/${projectId}/sequences/import?auto_annotate=${autoAnnotate}`,
      { formData: fd },
    )
  },
  importText: (projectId: string, payload: { content?: string; url?: string; filename?: string; auto_annotate?: boolean }) =>
    request<ImportResult>(`/projects/${projectId}/sequences/import-text`, { body: payload }),

  // tools
  enzymes: (params: { common_only?: boolean; search?: string } = {}) => {
    const q = new URLSearchParams()
    if (params.common_only) q.set('common_only', 'true')
    if (params.search) q.set('search', params.search)
    return request<{ count: number; common_set: string[]; enzymes: EnzymeInfo[]; total_catalogue: number }>(`/tools/enzymes?${q}`)
  },
  enzymeSearch: (payload: { sequence_id?: string; sequence?: string; circular?: boolean; enzymes?: string[]; common_only?: boolean; unique_only?: boolean }) =>
    request<EnzymeScanResult>('/tools/enzymes/search', { body: payload }),
  digest: (payload: { sequence_id?: string; sequence?: string; circular?: boolean; enzymes: string[]; ladder?: string; gel_percent?: number }) =>
    request<DigestResult>('/tools/digest', { body: payload }),
  suggestEnzymes: (payload: { sequence_id?: string; insert_start?: number; insert_end?: number }) =>
    request<{ pairs: EnzymeScanResult['suggestions'] }>('/tools/cloning/suggest-enzymes', { body: payload }),
  translate: (payload: { sequence_id?: string; sequence?: string; frame?: number; table_id?: number; six_frame?: boolean; to_stop?: boolean }) =>
    request<{ protein?: string; length?: number; molecular_weight?: number; isoelectric_point?: number; frames?: { frame: number; strand: number; offset: number; protein: string }[] }>('/tools/translate', { body: payload }),
  orfs: (payload: { sequence_id?: string; sequence?: string; circular?: boolean; min_aa?: number; table_id?: number }) =>
    request<{ orfs: Orf[]; count: number }>('/tools/orf', { body: payload }),
  analyzePrimer: (sequence: string) => request<PrimerStats>('/tools/primers/analyze', { body: { sequence } }),
  designPrimers: (payload: Record<string, unknown>) =>
    request<{ pairs: PrimerPair[]; count: number } | { job_id: string }>('/tools/primers/design', { body: payload }),
  sequencingPrimers: (payload: { sequence_id?: string; read_length?: number }) =>
    request<{ primers: (PrimerStats & { name: string; start: number; end: number })[]; count: number }>('/tools/primers/sequencing', { body: payload }),
  gibson: (payload: { insert: string; vector_left: string; vector_right: string; overlap?: number }) =>
    request<Record<string, unknown>>('/tools/primers/gibson', { body: payload }),
  pcr: (payload: { sequence_id?: string; sequence?: string; forward: string; reverse: string; max_mismatches?: number }) =>
    request<PcrResult>('/tools/pcr', { body: payload }),
  align: (payload: Record<string, unknown>) =>
    request<AlignResult | { job_id: string; status: string; type: string }>('/tools/align', { body: payload }),
  msa: (payload: { sequence_ids?: string[]; sequences?: { name: string; sequence: string }[] }) =>
    request<MsaResult | { job_id: string }>('/tools/align/multiple', { body: payload }),
  annotate: (payload: { sequence_id?: string; sequence?: string; include_orfs?: boolean; min_orf_aa?: number; apply?: boolean }) =>
    request<{ features: Omit<Feature, 'id' | 'sequence_id'>[]; count: number; applied?: number }>('/tools/annotate', { body: payload }),
  transferAnnotations: (payload: { reference_sequence_id: string; target_sequence_id: string; apply?: boolean; min_identity?: number }) =>
    request<{ transferred: Omit<Feature, 'id' | 'sequence_id'>[]; count: number; applied: boolean }>('/tools/annotate/transfer', { body: payload }),
  composition: (payload: { sequence_id?: string; sequence?: string; window?: number }) =>
    request<Record<string, unknown>>('/tools/composition', { body: payload }),

  // primers store
  storedPrimers: (projectId: string, sequenceId?: string) =>
    request<StoredPrimer[]>(`/projects/${projectId}/primers${sequenceId ? `?sequence_id=${sequenceId}` : ''}`),
  savePrimer: (projectId: string, payload: Record<string, unknown>) =>
    request<StoredPrimer>(`/projects/${projectId}/primers`, { body: payload }),
  deletePrimer: (id: string) => request<void>(`/primers/${id}`, { method: 'DELETE' }),

  // jobs
  jobs: (status?: string) => request<Page<Job>>(`/jobs?size=50${status ? `&status=${status}` : ''}`),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),
  deleteJob: (id: string) => request<void>(`/jobs/${id}`, { method: 'DELETE' }),

  // external registry
  externalResources: () => request<ExternalResource[]>('/external/resources?enabled_only=false'),
  createExternalResource: (payload: Record<string, unknown>) =>
    request<ExternalResource>('/external/resources', { body: payload }),
  updateExternalResource: (id: string, payload: Record<string, unknown>) =>
    request<ExternalResource>(`/external/resources/${id}`, { method: 'PATCH', body: payload }),
  deleteExternalResource: (id: string) => request<void>(`/external/resources/${id}`, { method: 'DELETE' }),
  renderExternalUrl: (id: string, params: Record<string, string>) =>
    request<{ url: string; kind: string }>(`/external/resources/${id}/url`, { body: { params } }),
  fetchExternal: (id: string, params: Record<string, string>, importTo?: string, autoAnnotate = false) =>
    request<{ resource: string; url: string; detected_format: string; preview: string; imported: { sequence_id: string; name: string; length: number }[] }>(
      `/external/resources/${id}/fetch`,
      { body: { params, import_to_project: importTo, auto_annotate: autoAnnotate } },
    ),
  proxyPolicy: () => request<{ enabled: boolean; allowlist: string[]; timeout_seconds: number }>('/external/proxy-policy'),
}

/** Poll a job until it settles (used for async analyses). */
export async function waitForJob(jobId: string, onTick?: (job: Job) => void, intervalMs = 700): Promise<Job> {
  for (;;) {
    const job = await api.job(jobId)
    onTick?.(job)
    if (job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled') return job
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

export function isJobRef(value: unknown): value is { job_id: string } {
  return !!value && typeof value === 'object' && 'job_id' in (value as Record<string, unknown>)
}
