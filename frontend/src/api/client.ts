/**
 * The server's API. Every call names this browser tab in `X-Nexbrand-Client` (changes without it are refused, the
 * wall against requests from other sites). Errors come back as `ApiError` with the server's code; the page builds
 * its sentence from `errors.<code>` in the language files.
 */

import type { BrandColor, BrandLogo, BrandSet } from '../lib/brand'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly values: Record<string, unknown> = {},
  ) {
    super(code)
  }
}

const CLIENT_KEY = 'nexbrand.client'
/** Sent on `window` when a request finds that the session is gone: the page goes back to the sign-in. */
export const SIGNED_OUT_EVENT = 'nexbrand:signed-out'

function randomId(): string {
  const bytes = new Uint8Array(12)
  crypto.getRandomValues(bytes)
  return 'tab-' + Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

let clientId: string | null = null

/** One id per tab: sessionStorage survives a reload of the tab but is not shared with other tabs. */
export function tabId(): string {
  if (clientId) return clientId
  try {
    clientId = sessionStorage.getItem(CLIENT_KEY)
    if (!clientId) {
      clientId = randomId()
      sessionStorage.setItem(CLIENT_KEY, clientId)
    }
  } catch {
    clientId = randomId()
  }
  return clientId
}

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, string | number | boolean | string[] | undefined>
  body?: unknown
  /** A file as the body (an upload), sent as it is. */
  raw?: Blob
  /** The answer is a file, not JSON. */
  blob?: boolean
}

const BUSY_TRIES = 3
const BUSY_WAIT_MS = 1500

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const repeatable = (options.method ?? 'GET') === 'GET'
  for (let attempt = 1; ; attempt++) {
    try {
      return await once<T>(path, options)
    } catch (error) {
      if (!(error instanceof ApiError && error.code === 'busy' && repeatable && attempt < BUSY_TRIES)) throw error
      await new Promise((resolve) => setTimeout(resolve, BUSY_WAIT_MS))
    }
  }
}

async function once<T>(path: string, options: Options): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (Array.isArray(value)) for (const item of value) url.searchParams.append(key, item)
    else if (value !== undefined) url.searchParams.set(key, String(value))
  }
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Nexbrand-Client': tabId() }
  let body: BodyInit | undefined
  if (options.raw) body = options.raw
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  const response = await fetch(url.pathname + url.search, { method: options.method ?? 'GET', headers, body })
  if (response.status === 204) return undefined as T
  if (options.blob && response.ok) return (await response.blob()) as T
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
      const { code, message: _message, ...values } = detail
      if (code === 'sign_in_required') window.dispatchEvent(new Event(SIGNED_OUT_EVENT))
      throw new ApiError(response.status, code, values)
    }
    throw new ApiError(response.status, response.status === 401 ? 'sign_in_required' : 'internal_error')
  }
  return data as T
}

/** An upload with progress (fetch cannot report it): resolves with the server's answer. */
export function upload<T>(path: string, query: Record<string, string | number>, file: Blob, onProgress?: (part: number) => void): Promise<T> {
  const url = new URL(path, window.location.origin)
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, String(value))
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', url.pathname + url.search)
    request.setRequestHeader('X-Nexbrand-Client', tabId())
    request.setRequestHeader('Accept', 'application/json')
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total)
    }
    request.onload = () => {
      let data: unknown = null
      try {
        data = JSON.parse(request.responseText)
      } catch {
        // no JSON
      }
      if (request.status >= 200 && request.status < 300) return resolve(data as T)
      const detail = (data as { detail?: { code?: string } } | null)?.detail
      reject(new ApiError(request.status, typeof detail?.code === 'string' ? detail.code : 'internal_error', (detail as Record<string, unknown>) ?? {}))
    }
    request.onerror = () => reject(new ApiError(0, 'network'))
    request.send(file)
  })
}

// ---- Types ----------------------------------------------------------------------------------------------------------

export type Role = 'read' | 'write' | 'manage'

export type Me = {
  id: number
  name: string
  display_name: string
  role: 'operator' | 'member'
  sign_in: 'password' | 'oidc'
  email: string
  language: string
  oidc_linked: boolean
  two_factor: boolean
  two_factor_recovery_left: number
  avatar: string | null
  version: string
  whats_new_seen: string
  shares_allowed?: boolean
  mail?: boolean
  second_factor_setup_required?: boolean
  upload_max_mb?: number
  preferences?: Preferences
  /** Connected to nexsuite: accounts, teams, rights, sign-in (and mail) are kept there. */
  suite?: '' | 'connecting' | 'connected'
  suite_mail?: boolean
  /** Connected: this account is the app's emergency account. */
  suite_emergency?: boolean
  /** Whether "New client" makes one here (not while nexsuite keeps the clients; else the operator's switch). */
  may_create_clients?: boolean
}

export type Preferences = {
  start: 'clients' | 'last'
  color_format: 'hex' | 'rgb' | 'hsl' | 'cmyk'
}

export type Member = { id: number; name: string; display_name: string; role: Role; avatar: string | null }

/** The group of rights behind one client: who has access, with which right. Never shown as a place of its own. */
export type SpaceInfo = {
  id: number
  name: string
  color: string
  role: Role | null
  /** The client whose group this is. */
  client: string | null
  members: Member[]
  /** The teams with a right in the client. */
  teams: TeamGrantInfo[]
  /** Its rights come from nexsuite. */
  managed?: boolean
}

export type TeamGrantInfo = { id: number; name: string; color: string; role: Role }

/** A team: who works together. */
export type Team = { id: number; name: string; color: string; lead: number | null; source: 'local' | 'admin'; members: number[]; size: number }

export type Person = { id: number; name: string; display_name: string; avatar: string | null }

export type Directory = { me: number; people: Person[]; teams: Team[] }

export type VersionInfo = {
  id: string
  label: string
  status: 'draft' | 'published'
  valid_from: string
  origin: 'hand' | 'collect' | 'mcp' | 'review'
  author: string
  note: string
  /** The version this one was made from, and its name then; null: started from a set given, or empty. */
  source_id: string | null
  source_label: string
  created_at: string
  updated_at: string
  published_at: string | null
  published_by: string
  data: BrandSet
}

export type ProjectInfo = { id: string; name: string; version_id: string; note: string; own: BrandColor[]; created_at: string; updated_at: string }

/** What the overview shows of a client: colours, the small logo and fonts of its current version. */
export type ClientFace = { colors: string[]; logo: BrandLogo | null; mark?: BrandLogo | null; fonts?: string[] }

export type ClientLink = { kind: 'website' | 'repo'; url: string; label: string }

export type ClientInfo = {
  id: string
  /** Its group of rights (members, teams, files). */
  space_id: number
  name: string
  color: string
  /** Kept in nexsuite: name, sector, contact, colour and who may see it are changed there. */
  managed: boolean
  sector: string
  contact: string
  /** The client's addresses, for collecting with a click; nexbrand's own, also for a client nexsuite keeps. */
  links: ClientLink[]
  created_at: string
  updated_at: string
  updated_by: string
  deleted_at: string | null
  favorite: boolean
  opened_at: string | null
  role: Role | null
  current: string | null
  drafts: number
  projects: number
  face: ClientFace
}

export type ReviewBrief = { id: number; version_id: string; status: 'open' | 'chosen' | 'closed'; chosen: string }

export type ClientWhole = Omit<ClientInfo, 'projects'> & {
  note: string
  versions: VersionInfo[]
  projects: ProjectInfo[]
  shares: number
  reviews: ReviewBrief[]
}

export type ShareInfo = {
  id: number
  label: string
  link: string
  version_id: string | null
  version_label: string | null
  views: number
  created_at: string
  expires_at: string | null
  password: boolean
}

export type Variant = { id: string; label: string; why?: string; data: BrandSet }
export type ReviewComment = { id?: number; variant: string; author: string; text: string; agency: boolean; at: string }

export type ReviewInfo = {
  id: number
  link: string
  version_id: string
  label: string
  sender: string
  message: string
  status: 'open' | 'chosen' | 'closed'
  chosen: string
  chosen_by: string
  chosen_at: string | null
  variants: Variant[]
  comments: ReviewComment[]
  created_at: string
  expires_at: string | null
}

export type FileInfo = { name: string; kind: string; size?: number }

export type PublicPageInfo = {
  password?: boolean
  client: string
  sector: string
  label: string
  version: { label: string; valid_from: string }
  design: BrandSet
  files: Record<string, FileInfo>
  token: string
}

export type ReviewPageInfo = {
  client: string
  sender: string
  message: string
  status: 'open' | 'chosen' | 'closed'
  chosen: string
  chosen_by: string
  variants: Variant[]
  comments: ReviewComment[]
  files: Record<string, FileInfo>
  expires_at: string | null
}

export type ExportFormat = 'css' | 'tailwind' | 'scss' | 'json'

export type MediaInfo = {
  id: string
  name: string
  kind: string
  mime: string
  size: number
  width: number
  height: number
  pages: number
  removed: string[]
  known: boolean
}

export type SetupState = { needs_setup: boolean; code_required: boolean; signed_in: boolean; version: string; min_password: number }
export type Methods = { password: boolean; oidc: boolean; oidc_name: string; suite?: boolean }

export type AiAccess = { active: boolean; url: string; model: string; key_set: boolean }
export type AiState = { allowed: boolean; ready: boolean; access: AiAccess }
export type AiModel = { id: string; name: string }
export type AiEvent = { id: number; at: string; model: string; task: 'order' | 'directions'; tokens_in: number; tokens_out: number; error: string; body: unknown }
export type Direction = { label: string; why: string; hue: number; accent_hue: number; saturation: number; mood: string; head: string; body: string }

export type SourceKind = 'website' | 'repo' | 'pdf'
export type FoundColor = {
  hex: string
  share: number
  where: string[]
  names: string[]
  detail: string
  pantone: string
  cmyk: string
  role: 'primary' | 'secondary' | 'accent' | 'neutral'
  name: string
  keep: boolean
  reason: string
  /** A framework's colour (Bootstrap and the like), not the brand's: left out until a person ticks it. */
  framework?: boolean
}
export type FontFileFound = { url: string; weight: string; style: string }
export type FontFileTaken = { id: string; name: string; kind: string; weight: string; style: string }
export type FoundFont = { family: string; where: string[]; license: 'free' | 'unknown'; detail: string; use: 'headings' | 'body' | 'other'; keep: boolean; files: FontFileFound[] }
export type FoundLogo = { url: string; kind: string; where: string }
export type Collected = {
  colors: FoundColor[]
  fonts: FoundFont[]
  logos: FoundLogo[]
  notes: { source: string; problem: string }[]
  ai: boolean
  /** The device's own font, when the page uses it (a stack like `-apple-system, Segoe UI, Roboto`), else empty. */
  system_font: string
}

// ---- Calls ----------------------------------------------------------------------------------------------------------

export const authApi = {
  setupState: () => api<SetupState>('/api/setup'),
  setup: (name: string, password: string, code: string, language: string) =>
    api<Me>('/api/setup', { method: 'POST', body: { name, password, code, language } }),
  methods: () => api<Methods>('/api/auth/methods'),
  login: (name: string, password: string) => api<Me | { second_factor: true }>('/api/auth/login', { method: 'POST', body: { name, password } }),
  code: (code: string) => api<Me>('/api/auth/login/totp', { method: 'POST', body: { code } }),
  cancelCode: () => api<void>('/api/auth/login/totp/cancel', { method: 'POST' }),
  logout: () => api<void>('/api/auth/logout', { method: 'POST' }),
  me: () => api<Me>('/api/auth/me'),
  language: (language: string) => api<Me>('/api/me/language', { method: 'PUT', body: { language } }),
  preferences: (change: Partial<Preferences>) => api<Preferences>('/api/me/preferences', { method: 'PUT', body: change }),
  profile: (display_name: string) => api<Me>('/api/me/profile', { method: 'PUT', body: { display_name } }),
  password: (current: string, next: string) => api<void>('/api/auth/password', { method: 'PUT', body: { current, new: next } }),
  whatsNewSeen: () => api<Me>('/api/me/whats-new/seen', { method: 'POST' }),
}

export const spacesApi = {
  list: () => api<SpaceInfo[]>('/api/spaces'),
  members: (id: number) =>
    api<{ space: string; members: { name: string; role: Role; you: boolean }[]; invites: Invite[]; role: Role | null; suite?: boolean; managed?: boolean }>(
      `/api/spaces/${id}/members`,
    ),
  setMember: (id: number, name: string, role: Role) =>
    api<{ name: string; role: Role; invited?: boolean }>(`/api/spaces/${id}/members/${encodeURIComponent(name)}`, { method: 'PUT', body: { role } }),
  removeMember: (id: number, name: string) => api<void>(`/api/spaces/${id}/members/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  invite: (id: number, role: Role, days = 7) => api<Invite & { link: string }>(`/api/spaces/${id}/invites`, { method: 'POST', body: { role, days } }),
  /** A team's right in the space; `null` takes it away. */
  teamRight: (id: number, team: number, role: Role | null) =>
    role
      ? api<SpaceInfo>(`/api/spaces/${id}/teams/${team}`, { method: 'PUT', body: { role } })
      : api<SpaceInfo | { id: number; gone: true }>(`/api/spaces/${id}/teams/${team}`, { method: 'DELETE' }),
}

export type TeamChange = { name?: string; color?: string; members?: number[]; lead?: number | null }

export const directoryApi = {
  get: () => api<Directory>('/api/directory'),
  create: (team: { name: string; color: string; members: number[]; lead: number | null }) => api<Team>('/api/teams', { method: 'POST', body: team }),
  change: (id: number, change: TeamChange) => api<Team>(`/api/teams/${id}`, { method: 'PATCH', body: change }),
  remove: (id: number) => api<void>(`/api/teams/${id}`, { method: 'DELETE' }),
}

export type ApiToken = {
  id: number
  name: string
  level: 'read'
  prefix: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  blocked: boolean
  /** The clients it may see; null: every client its account may read. */
  clients: { id: string; name: string }[] | null
}
export type AnyApiToken = Omit<ApiToken, 'clients'> & { account: string; clients: number | null }

/** API tokens for programs (`/api/v1`); reading only. */
export const apiTokensApi = {
  list: () => api<{ allowed: boolean; tokens: ApiToken[] }>('/api/api-tokens'),
  make: (name: string, clients: string[] | null, days: number | null, level: 'read' | 'draft' = 'read') =>
    api<{ token: ApiToken; secret: string }>('/api/api-tokens', { method: 'POST', body: { name, clients, days, level } }),
  remove: (id: number) => api<void>(`/api/api-tokens/${id}`, { method: 'DELETE' }),
  every: () => api<AnyApiToken[]>('/api/admin/api-tokens'),
  block: (id: number) => api<AnyApiToken>(`/api/admin/api-tokens/${id}/block`, { method: 'POST' }),
}

export type Invite = { id: number; role: string; email: string; by: string | null; created_at: string; expires_at: string }

export const clientsApi = {
  list: (query: { deleted?: boolean } = {}) => api<ClientInfo[]>('/api/clients', { query }),
  read: (id: string) => api<ClientWhole>(`/api/clients/${id}`),
  /** A client; `label` empty: without a design set yet. */
  create: (body: { name: string; color?: string; sector?: string; contact?: string; note?: string; label: string; data?: BrandSet; project?: string }) =>
    api<ClientWhole>('/api/clients', { method: 'POST', body }),
  change: (id: string, change: { name?: string; color?: string; sector?: string; contact?: string; note?: string; links?: ClientLink[]; favorite?: boolean }) =>
    api<ClientInfo>(`/api/clients/${id}`, { method: 'PATCH', body: change }),
  visit: (id: string) => api<void>(`/api/clients/${id}/visit`, { method: 'POST' }),
  files: (id: string) => api<Record<string, FileInfo & { width?: number; height?: number }>>(`/api/clients/${id}/files`),
  trash: (id: string) => api<void>(`/api/clients/${id}`, { method: 'DELETE' }),
  restore: (id: string) => api<ClientInfo>(`/api/clients/${id}/restore`, { method: 'POST' }),
  purge: (id: string) => api<void>(`/api/clients/${id}/purge`, { method: 'DELETE' }),
  newVersion: (id: string, body: { label: string; source?: string; data?: BrandSet; note?: string; origin?: 'hand' | 'collect' }) =>
    api<VersionInfo>(`/api/clients/${id}/versions`, { method: 'POST', body }),
  saveDraft: (id: string, version: string, change: { label?: string; note?: string; data?: BrandSet }) =>
    api<VersionInfo>(`/api/clients/${id}/versions/${version}`, { method: 'PUT', body: change }),
  publish: (id: string, version: string, body: { valid_from?: string; label?: string }) =>
    api<VersionInfo>(`/api/clients/${id}/versions/${version}/publish`, { method: 'POST', body }),
  deleteDraft: (id: string, version: string) => api<void>(`/api/clients/${id}/versions/${version}`, { method: 'DELETE' }),
  exportText: (id: string, query: { format: ExportFormat; version?: string; project?: string }) =>
    fetch(`/api/clients/${encodeURIComponent(id)}/export?` + new URLSearchParams(Object.entries(query).filter(([, v]) => v) as [string, string][]).toString(), {
      headers: { 'X-Nexbrand-Client': tabId() },
    }).then((r) => (r.ok ? r.text() : Promise.reject(new ApiError(r.status, 'internal_error')))),
  exportUrl: (id: string, query: { format: ExportFormat; version?: string; project?: string }) =>
    `/api/clients/${encodeURIComponent(id)}/export?` + new URLSearchParams([...Object.entries(query).filter(([, v]) => v), ['download', 'true']] as [string, string][]).toString(),
  newProject: (id: string, body: { name: string; version_id: string; note?: string; own?: BrandColor[] }) =>
    api<ProjectInfo>(`/api/clients/${id}/projects`, { method: 'POST', body }),
  changeProject: (id: string, project: string, change: { name?: string; note?: string; version_id?: string; own?: BrandColor[] }) =>
    api<ProjectInfo>(`/api/clients/${id}/projects/${project}`, { method: 'PATCH', body: change }),
  deleteProject: (id: string, project: string) => api<void>(`/api/clients/${id}/projects/${project}`, { method: 'DELETE' }),
}

export const sharesApi = {
  list: (client: string) => api<ShareInfo[]>(`/api/clients/${client}/shares`),
  create: (client: string, body: { label: string; version_id?: string | null; days?: number | null; password?: string }) =>
    api<ShareInfo>(`/api/clients/${client}/shares`, { method: 'POST', body }),
  change: (id: number, change: { label?: string; days?: number; forever?: boolean; password?: string; no_password?: boolean }) =>
    api<ShareInfo>(`/api/shares/${id}`, { method: 'PATCH', body: change }),
  remove: (id: number) => api<void>(`/api/shares/${id}`, { method: 'DELETE' }),
  page: (token: string) => api<PublicPageInfo>(`/api/public/${token}`),
  unlock: (token: string, password: string) => api<PublicPageInfo>(`/api/public/${token}`, { method: 'POST', body: { password } }),
}

export const reviewsApi = {
  list: (client: string) => api<ReviewInfo[]>(`/api/clients/${client}/reviews`),
  create: (client: string, body: { version_id: string; variants: Variant[]; label: string; sender?: string; message?: string; days?: number }) =>
    api<ReviewInfo>(`/api/clients/${client}/reviews`, { method: 'POST', body }),
  comment: (client: string, review: number, variant: string, text: string) =>
    api<ReviewInfo>(`/api/clients/${client}/reviews/${review}/comments`, { method: 'POST', body: { variant, text } }),
  withdraw: (client: string, review: number) => api<void>(`/api/clients/${client}/reviews/${review}`, { method: 'DELETE' }),
  page: (token: string) => api<ReviewPageInfo>(`/api/review/${token}`),
  say: (token: string, variant: string, author: string, text: string) =>
    api<ReviewPageInfo>(`/api/review/${token}/comments`, { method: 'POST', body: { variant, author, text } }),
  choose: (token: string, variant: string, author: string) =>
    api<ReviewPageInfo>(`/api/review/${token}/choose`, { method: 'POST', body: { variant, author } }),
}

export const mediaApi = {
  upload: (space: number, file: File | Blob, name: string, onProgress?: (part: number) => void) =>
    upload<MediaInfo>('/api/media', { space, name }, file, onProgress),
}

const safeId = (id: string) => (/^[A-Za-z0-9_-]{8,40}$/.test(id) ? id : 'invalid0')

/** Where a file of a brand is shown from. Only ever built from an id, never from what a design set says. */
export function mediaUrl(id: string, preview = false): string {
  return `/api/media/${safeId(id)}${preview ? '?preview=1' : ''}`
}

/** The same for a public page or a review: the page's token opens only the files that page shows. */
export function pageMediaUrl(kind: 'public' | 'review', token: string, id: string): string {
  return `/api/${kind}/${encodeURIComponent(token)}/media/${safeId(id)}`
}

export function avatarUrl(person: { id: number; avatar: string | null }): string | null {
  return person.avatar ? `/api/avatars/${person.id}?v=${encodeURIComponent(person.avatar)}` : null
}

export const aiApi = {
  state: () => api<AiState>('/api/ai'),
  save: (change: Partial<{ active: boolean; url: string; model: string; key: string }>) => api<AiState>('/api/ai', { method: 'PUT', body: change }),
  models: (url?: string, key?: string) => api<AiModel[]>('/api/ai/models', { method: 'POST', body: { url, key } }),
  directions: (brief: string, name: string, language: string) =>
    api<{ directions: Direction[] }>('/api/ai/directions', { method: 'POST', body: { brief, name, language } }),
  events: () => api<AiEvent[]>('/api/ai/events'),
  clear: () => api<{ removed: number }>('/api/ai/events', { method: 'DELETE' }),
}

export const collectApi = {
  run: (sources: { kind: SourceKind; value: string }[], useAi: boolean, language: string) =>
    api<Collected>('/api/collect', { method: 'POST', body: { sources, use_ai: useAi, language } }),
  logo: (clientId: string, url: string) => api<MediaInfo>('/api/collect/logo', { method: 'POST', body: { client_id: clientId, url } }),
  /** A found logo as the server fetched it: the page never loads it from the other website itself. */
  previewUrl: (url: string) => `/api/collect/preview?url=${encodeURIComponent(url)}`,
  /** A font's files, only with the licence confirmed (`licensed`). */
  fonts: (clientId: string, family: string, files: FontFileFound[], licensed: boolean) =>
    api<{ files: FontFileTaken[]; notes: { source: string; problem: string }[] }>('/api/collect/fonts', { method: 'POST', body: { client_id: clientId, family, files, licensed } }),
}
