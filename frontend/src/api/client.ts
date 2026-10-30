import axios from 'axios'
import { ensureFreshToken, logout } from '../auth/keycloak'
import { ensureFreshPlatformToken, platformLogout } from '../auth/platformKeycloak'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL + '/api/v1',
})

// Two independent auth contexts share this client: the tenant app and
// the Product-Owner console (/glbadmin, separate `platform` realm). Pick
// the token by path — console pages only ever run under /glbadmin.
const onConsole = () => window.location.pathname.startsWith('/glbadmin')

// Async interceptor: refresh the token if near expiry BEFORE attaching it,
// so a lapsed token never causes a spurious 401 → "save failed" / logout.
api.interceptors.request.use(async (config) => {
  const token = onConsole() ? await ensureFreshPlatformToken() : await ensureFreshToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// keycloak-js onTokenExpired handles most refreshes proactively, but
// the server can still reject (token revoked, issuer mismatch after a
// tenant's idp_url changed, JWKS rotated outside our 5-min cache TTL).
// Bounce the user back through the email-entry → login chain instead
// of letting the UI sit on a stale session.
let loggingOut = false
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && !loggingOut) {
      loggingOut = true
      onConsole() ? platformLogout() : logout()
    }
    return Promise.reject(err)
  },
)

export interface ActivityEntry {
  id: string
  timestamp: string
  user_name: string | null
  action: string
  details: { query?: string; query_type?: string; purpose?: string | null; [k: string]: any }
}

export const casesApi = {
  list: () => api.get('/cases').then((r) => r.data),
  /** Who searched what, when and why — from the customer's own store. */
  activity: (id: string): Promise<{ entries: ActivityEntry[] }> =>
    api.get(`/cases/${id}/activity`).then((r) => r.data),
  /** "Which of my cases moved?" — aggregation over jobs, alerts and
   *  timestamps that already exist. No agent round-trip. */
  overview: () => api.get('/cases/overview').then((r) => r.data),
  /** When would this case be deleted, and what suspends it. */
  retention: (id: string) => api.get(`/cases/${id}/retention`).then((r) => r.data),
  create: (data: { title: string; description?: string; priority?: string
                   restricted?: boolean; members?: string[]; template?: string | null }) =>
    api.post('/cases', data).then((r) => r.data),
  /** Names to offer for assignee/members — IdP where readable, else history. */
  assignableUsers: (): Promise<{ users: string[]; source: 'idp' | 'history' }> =>
    api.get('/cases/assignable-users').then((r) => r.data),
  get: (id: string) => api.get(`/cases/${id}`).then((r) => r.data),
  update: (id: string, data: object) => api.put(`/cases/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/cases/${id}`).then((r) => r.data),
}

export interface Playbook {
  key: string
  modules: string[]
  query_types: string[]
  next_steps: string[]
  /** Report outline a case opened with this template starts from. */
  report_sections: string[]
  /** False when the playbook does not fit the selector type currently typed. */
  applies: boolean
  unavailable_modules: string[]
}

export const searchApi = {
  start: (data: {
    query: string; query_type: string; case_id: string; modules: string[]
    /** Narrowing terms appended to `query`; free-text selectors only
     *  (keyword, company_name, person_name — see utils/facets.ts). */
    facets?: string[]
    /** Narrow the run to named tools of the selected modules.
     *  Empty or omitted = every tool, which is the backend default. */
    tools?: string[]
    /** Why this search is run (file number, order, legal basis). Goes only
     *  to the customer's activity log. Mandatory when the tenant requires it. */
    purpose?: string
  }) => api.post('/search', data).then((r) => r.data),
  status: (jobId: string) => api.get(`/search/${jobId}`).then((r) => r.data),
  /** Stop a running search. Findings already flushed stay in the case —
   *  the job ends as `cancelled`, which is not `failed`. */
  cancel: (jobId: string) => api.post(`/search/${jobId}/cancel`).then((r) => r.data),
  // Module presets per offence type. Server-filtered to what this tenant can
  // actually run, so a preset can never produce a 403 on submit.
  playbooks: (queryType?: string): Promise<{ playbooks: Playbook[] }> =>
    api.get('/search/playbooks', { params: queryType ? { query_type: queryType } : {} })
      .then((r) => r.data),
  // Newest job for a case (or {job:null}) — used to resume a running
  // search after a browser refresh / tab switch.
  latestForCase: (caseId: string) =>
    api.get(`/cases/${caseId}/latest-search`).then((r) => r.data.job),
  modules: () => api.get('/search/modules').then((r) => r.data),
  // Interactive "Erweiterte Suche": run modules and return candidate
  // entities+edges WITHOUT persisting (analyst then cherry-picks).
  // `tools` narrows the run to individual tools of the selected modules.
  // Omit it (or send []) to run every tool the modules offer — that is what
  // the ordinary search form does and what the backend treats as the default.
  preview: (data: { query: string; query_type: string; case_id: string;
                    modules: string[]; tools?: string[] }) =>
    api.post('/search/preview', data).then((r) => r.data),

  /**
   * Streaming preview: the same run, but progress and ranked candidates
   * arrive WHILE it happens instead of after up to five minutes of nothing.
   *
   * Uses `fetch` rather than axios because axios cannot expose a response
   * body as a stream in the browser. Abort by calling the returned function
   * (or via the passed AbortSignal) — the backend cancels the whole module
   * fan-out when the connection drops, so cancelling actually stops work
   * rather than just hiding it.
   *
   * Nothing is stored server-side: findings live in the worker's memory for
   * the life of this request only. That is deliberate — see the endpoint's
   * docstring.
   */
  previewStream: async (
    data: { query: string; query_type: string; case_id: string;
            modules: string[]; tools?: string[] },
    onMessage: (msg: any) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    const token = onConsole() ? await ensureFreshPlatformToken() : await ensureFreshToken()
    const res = await fetch(
      `${import.meta.env.VITE_API_URL}/api/v1/search/preview/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(data),
        signal,
      },
    )
    if (!res.ok || !res.body) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json())?.detail || detail } catch { /* not JSON */ }
      throw new Error(detail)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // NDJSON: a chunk can split a line, so keep the tail until its newline.
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.trim()) continue
        try { onMessage(JSON.parse(line)) } catch { /* ignore a torn line */ }
      }
    }
  },
}

export interface CaseDelta {
  job: { job_id: string; query: string; query_type: string; modules_used: string[]
         status: string; started_at: string; completed_at: string | null } | null
  previous_job: { job_id: string; query: string; started_at: string } | null
  since: string | null
  entities: any[]
  edges: any[]
  counts?: { entities: number; edges: number }
  note?: string
}

/**
 * Daily situation report. Public sources only — press, CISA KEV and
 * ransomware leak-site postings; nothing derived from case data, which is
 * why it lives framework-side like the news cache.
 */
export const digestApi = {
  get: (hours = 24, kevDays = 14) =>
    api.get('/digest', { params: { hours, kev_days: kevDays } }).then((r) => r.data),
}

export interface CrossHits {
  matches: Record<string, { case_id: string; entity_id: string }[]>
  cases: Record<string, { case_number: string; title: string; status: string }>
  available: boolean
}

export const graphApi = {
  getGraph: (caseId: string) => api.get(`/cases/${caseId}/graph`).then((r) => r.data),
  /** Findings of this case that also occur in cases the caller may open. */
  crossHits: (caseId: string): Promise<CrossHits> =>
    api.get(`/cases/${caseId}/cross-hits`).then((r) => r.data),
  getEntities: (caseId: string) => api.get(`/cases/${caseId}/entities`).then((r) => r.data),
  // What the last run ADDED. Additions only — the backend deliberately does
  // not track removals, and the UI has to say so rather than let an empty
  // "removed" column read as "nothing disappeared".
  getDelta: (caseId: string, jobId?: string): Promise<CaseDelta> =>
    api.get(`/cases/${caseId}/delta`, { params: jobId ? { job_id: jobId } : {} })
      .then((r) => r.data),

  // Selectors present in the case that no search has ever used. Computed
  // from the case's entities joined against its search_jobs — no new
  // collection, nothing stored.
  /** Mark many findings at once. is_relevant=null clears the mark —
   *  "I looked and I am not sure" stays reachable. */
  // Remove many findings at once, with their edges. One agent round trip —
  // a type can hold hundreds of rows.
  bulkDelete: (caseId: string, entity_ids: string[]) =>
    api.post(`/cases/${caseId}/entities/delete`, { entity_ids }).then((r) => r.data),
  bulkRelevance: (caseId: string, entityIds: string[], isRelevant: boolean | null) =>
    api.post(`/cases/${caseId}/entities/relevance`,
             { entity_ids: entityIds, is_relevant: isRelevant }).then((r) => r.data),

  getWorklist: (caseId: string, limit = 50) =>
    api.get(`/cases/${caseId}/worklist`, { params: { limit } })
      .then((r) => r.data),
}

// AI function (KI-Verknüpfung) — button-triggered case linking. Returns
// suggestions only (clusters / suggested edges / narrative / next steps);
// nothing is persisted. Requires the tenant's ai_enabled license.
export const aiApi = {
  // async: start a job, then poll linkStatus (avoids proxy/Cloudflare timeouts).
  link: (caseId: string): Promise<{ job_id: string; status: string }> =>
    api.post(`/cases/${caseId}/ai-link`).then((r) => r.data),
  linkStatus: (caseId: string, jobId: string): Promise<{ status: string; suggestions?: any; entities_sent?: number; note?: string | null; detail?: string }> =>
    api.get(`/cases/${caseId}/ai-link/${jobId}`).then((r) => r.data),
  apply: (caseId: string, edges: { from_id: string; to_id: string; relation: string; confidence?: number }[]): Promise<{ applied: number }> =>
    api.post(`/cases/${caseId}/ai-link/apply`, { edges }).then((r) => r.data),
}

export const auditApi = {
  list: (limit = 200, action?: string): Promise<{ total: number; entries: any[] }> =>
    api.get('/audit', { params: { limit, action } }).then((r) => r.data),
  verify: (): Promise<{ ok: boolean; checked: number; broken_at?: number }> =>
    api.get('/audit/verify').then((r) => r.data),
}

export const entityApi = {
  // Every call by entity/edge id carries its case: the server
  // checks the case is visible to the caller and the store checks the row
  // belongs to it.
  setRelevant: (caseId: string, id: string, value: boolean | null) =>
    api.patch(`/entities/${id}`, { is_relevant: value }, { params: { case_id: caseId } }).then((r) => r.data),
  rename: (caseId: string, id: string, label: string) =>
    api.patch(`/entities/${id}`, { label }, { params: { case_id: caseId } }).then((r) => r.data),
  // The investigator's own assessment. Lands in the CUSTOMER's database,
  // not the operator's — it is case-file content.
  setNotes: (caseId: string, id: string, notes: string) =>
    api.patch(`/entities/${id}`, { notes }, { params: { case_id: caseId } }).then((r) => r.data),
  delete: (caseId: string, id: string) =>
    api.delete(`/entities/${id}`, { params: { case_id: caseId } }).then((r) => r.data),
  // Persist a chosen subset of preview candidates into the case.
  commit: (caseId: string, data: { entities: any[]; edges: any[] }) =>
    api.post(`/cases/${caseId}/entities/commit`, data).then((r) => r.data),
  // Retract a link the investigator drew by hand. The server refuses
  // anything a tool asserted (409) — this is not a client-side rule.
  /** Fold `sourceIds` into `targetId` — edges, sources and names move over. */
  merge: (caseId: string, targetId: string, sourceIds: string[]) =>
    api.post(`/cases/${caseId}/entities/merge`, { target_id: targetId, source_ids: sourceIds }).then((r) => r.data),
  deleteEdge: (caseId: string, id: string) =>
    api.delete(`/edges/${id}`, { params: { case_id: caseId } }).then((r) => r.data),
  // How the investigator arranged the case map. Case content — it lives in
  // the customer's store, not here.
  getLayout: (caseId: string) =>
    api.get(`/cases/${caseId}/layout`).then((r) => r.data),
  putLayout: (caseId: string, layout: any) =>
    api.put(`/cases/${caseId}/layout`, layout).then((r) => r.data),
}

export interface AdminUser {
  id: string
  username: string
  email?: string
  first_name?: string
  last_name?: string
  enabled: boolean
  roles: string[]
  required_actions?: string[]
}

export const adminApi = {
  listUsers:   (): Promise<AdminUser[]> => api.get('/admin/users').then((r) => r.data),
  createUser:  (data: {
    username: string; email: string; password: string;
    first_name?: string; last_name?: string;
    roles?: string[]; temporary_password?: boolean;
  }) => api.post('/admin/users', data).then((r) => r.data),
  updateUser:  (id: string, data: Partial<AdminUser> & { roles?: string[] }) =>
    api.put(`/admin/users/${id}`, data).then((r) => r.data),
  deleteUser:  (id: string) => api.delete(`/admin/users/${id}`),
  resetPassword: (id: string, password: string, temporary = true) =>
    api.post(`/admin/users/${id}/reset-password`, { password, temporary }),
  reset2fa:    (id: string): Promise<{ removed: number }> =>
    api.post(`/admin/users/${id}/reset-2fa`).then((r) => r.data),
  setRequiredActions: (id: string, required_actions: string[]): Promise<{ required_actions: string[] }> =>
    api.put(`/admin/users/${id}/required-actions`, { required_actions }).then((r) => r.data),
  disable2faRequirement: (id: string): Promise<{ required_actions: string[]; removed_totp_requirement: boolean }> =>
    api.post(`/admin/users/${id}/disable-2fa-requirement`).then((r) => r.data),
  enable2faRequirement: (id: string): Promise<{ required_actions: string[]; added_totp_requirement: boolean }> =>
    api.post(`/admin/users/${id}/enable-2fa-requirement`).then((r) => r.data),
  listRoles:   (): Promise<{ name: string; description?: string }[]> =>
    api.get('/admin/roles').then((r) => r.data),
}

// License + Settings tabs in the Admin panel.
export interface TenantSettings {
  tenant: string
  display_name?: string | null
  logo_b64?: string | null
  default_alert_email?: string | null
  session_timeout_minutes?: number | null
  auto_delete_months?: number | null
  default_language?: 'de' | 'fr' | 'it' | 'en' | null
  require_search_purpose?: boolean
  default_playbook?: string | null
  report_classification?: string | null
  disabled_modules?: string[]
  /** Read-only: what the licence allows (the admin may switch these off). */
  licensed_modules?: string[]
}

export interface SelfTestCheck {
  key: string
  status: 'ok' | 'warn' | 'fail' | 'info'
  params: Record<string, any>
}

export interface LicenseInfo {
  tenant: string
  is_active: boolean
  valid_until: string
  days_remaining: number
  is_expired: boolean
  license_key_masked: string
  agent_api_key_masked: string
  agent_url: string | null
  idp_url: string | null
  email_domains: string[]
  // null / empty = all modules licensed. Operator-set; read-only here.
  enabled_modules: string[] | null
  // Licensable AI function (opt-in). Operator-set; read-only here.
  ai_enabled?: boolean
  contact_email: string
  created_at: string
}

// Alert delivery, configured by the customer's own admin. Secrets are
// write-only across this boundary: the server reports `*_set: boolean` and
// never returns a stored password, so the form shows an empty field with a
// "stored" hint rather than round-tripping a credential into the browser.
export interface NotificationSettings {
  tenant: string
  notify_email_enabled: boolean
  smtp_host?: string | null
  smtp_port: number
  smtp_security: 'starttls' | 'ssl' | 'none'
  smtp_username?: string | null
  smtp_password_set: boolean
  smtp_from?: string | null
  smtp_verify_tls: boolean
  notify_webhook_enabled: boolean
  webhook_url?: string | null
  webhook_secret_set: boolean
  notify_events: string[]
  notify_last_ok_at?: string | null
  notify_last_attempt_at?: string | null
  notify_last_error?: string | null
  default_alert_email?: string | null
  unregistered?: boolean
}

// Omit a secret to keep it, '' to clear it, a value to replace it. Without
// the three-way distinction there is no way to say "leave the password
// alone" from a form that never received it.
export interface NotificationSettingsUpdate {
  notify_email_enabled?: boolean
  smtp_host?: string | null
  smtp_port?: number
  smtp_security?: string
  smtp_username?: string | null
  smtp_password?: string
  smtp_from?: string | null
  smtp_verify_tls?: boolean
  notify_webhook_enabled?: boolean
  webhook_url?: string | null
  webhook_secret?: string
  notify_events?: string[]
}

export interface DeliveryResult {
  channel: string
  ok: boolean
  detail: string
  duration_ms: number
}

export const tenantApi = {
  getSettings: (): Promise<TenantSettings> => api.get('/admin/settings').then((r) => r.data),
  updateSettings: (data: Partial<TenantSettings>): Promise<{ ok: boolean }> =>
    api.put('/admin/settings', data).then((r) => r.data),
  getLicense: (): Promise<LicenseInfo> => api.get('/admin/license').then((r) => r.data),
  /** Is a newer customer-agent release published than the one running? */
  updateStatus: (): Promise<{
    state: 'outdated' | 'current' | 'unknown'; installed?: string | null; latest?: string | null
    released_at?: string | null; changes?: Record<string, string[]>; command?: string
  }> => api.get('/admin/update-status').then((r) => r.data),
  /** Health + configuration of this authority's installation (admin only). */
  selftest: (): Promise<{ overall: 'ok' | 'warn' | 'fail'; checked_at: string; checks: SelfTestCheck[] }> =>
    api.get('/admin/selftest').then((r) => r.data),
  getNotifications: (): Promise<NotificationSettings> =>
    api.get('/admin/notification-settings').then((r) => r.data),
  updateNotifications: (data: NotificationSettingsUpdate): Promise<NotificationSettings> =>
    api.put('/admin/notification-settings', data).then((r) => r.data),
  testNotification: (channel: 'email' | 'webhook', recipient?: string): Promise<DeliveryResult> =>
    api.post('/admin/notification-settings/test', { channel, recipient }).then((r) => r.data),
}

// Alerts. The dashboard tile only means something because the alert chain
// actually writes alerts; a 0 here is a statement, not a placeholder.
export interface AlertRow {
  id: string
  case_id: string
  case_title?: string | null
  case_number?: string | null
  entity_id: string
  monitoring_config_id: string
  change_type: string
  // Stored operator-side: identifiers and categories only — never the
  // finding. See backend services/alerting.py.
  old_value?: Record<string, unknown> | null
  new_value?: Record<string, unknown> | null
  is_read: boolean
  created_at?: string | null
  // Resolved from the CUSTOMER's store at read time, not stored here.
  // `resolved: false` means the agent could not be reached — the alert is
  // still real, we just cannot name what it points at right now.
  entity_label?: string | null
  entity_url?: string | null
  admiralty?: string | null
  resolved?: boolean
}

export interface AlertTrigger { value: string; description: string }
export interface UnavailableTrigger { value: string; reason: string; mapped_to?: string | null }

export const alertsApi = {
  list: (unreadOnly = false, limit = 100): Promise<{ alerts: AlertRow[] }> =>
    api.get('/alerts', { params: { unread_only: unreadOnly, limit } }).then((r) => r.data),
  markRead: (alertIds?: string[], isRead = true): Promise<{ updated: number }> =>
    api.post('/alerts/read', { alert_ids: alertIds, is_read: isRead }).then((r) => r.data),
  triggers: (): Promise<{ available: AlertTrigger[]; unavailable: UnavailableTrigger[]
                          legacy_map: Record<string, string> }> =>
    api.get('/monitoring/triggers').then((r) => r.data),
}

// Global/Platform Admin (operator panel, /glbadmin). All routes
// are gated by the platform_admin realm role; the operator manages
// tenants/licenses/docker-wiring but never sees investigation data.
export interface Contact {
  name: string
  email?: string | null
  phone?: string | null
  role?: string | null
}

export interface ProductOwner {
  id: string
  username: string
  email?: string | null
  enabled: boolean
}

export interface TenantSummary {
  tenant: string
  is_active: boolean
  valid_until: string
  days_remaining: number
  is_expired: boolean
  contact_email: string
  display_name?: string | null
  agent_url?: string | null
  idp_url?: string | null
  email_domains: string[]
  enabled_modules: string[] | null
  contacts?: Contact[]
  created_at: string
}

export interface TenantDetail extends TenantSummary {
  license_key_masked?: string
  agent_api_key_masked?: string
  logo_b64?: string | null
  default_alert_email?: string | null
  session_timeout_minutes?: number | null
  auto_delete_months?: number | null
  ai_enabled?: boolean
}

export interface CreateTenantPayload {
  tenant: string
  contact_email: string
  valid_days?: number
  agent_url?: string | null
  idp_url?: string | null
  idp_backend_secret?: string | null
  email_domains?: string[] | null
  enabled_modules?: string[] | null
  display_name?: string | null
}

export interface CreatedTenant {
  tenant: string
  license_key: string
  agent_api_key: string
  valid_until: string
}

export interface AgentHealth {
  reachable: boolean
  status_code?: number
  agent_url: string | null
  health?: unknown
  detail?: string
}

export interface MetricsSummary {
  tenants_total: number
  tenants_active: number
  tenants_expired: number
  tenants_expiring_30d: number
  modules_loaded: string[]
  modules_count: number
}

export interface SystemHealth {
  status: 'ok' | 'degraded' | 'down'
  infra: Record<string, string>
  modules: { name: string; status: string; tools: number; detail?: string }[]
  modules_total: number
  modules_ok: number
  tools_total: number
  problems: { infra: string[]; down: string[]; degraded: string[] }
  grafana_url: string
}

export const platformApi = {
  /** Is the FRAMEWORK healthy — postgres, redis, licence server, 14 modules. */
  systemHealth: (): Promise<SystemHealth> =>
    api.get('/platform/system-health').then((r) => r.data),
  /**
   * The operator's OWN action log. Pinned server-side to the platform
   * tenant — there is no parameter that could widen it to a customer's
   * audit trail (operator/tenant boundary).
   */
  audit: (limit = 200): Promise<{ total: number; entries: any[] }> =>
    api.get('/platform/audit', { params: { limit } }).then((r) => r.data),
  listTenants: (): Promise<TenantSummary[]> => api.get('/platform/tenants').then((r) => r.data),
  getTenant: (t: string): Promise<TenantDetail> => api.get(`/platform/tenants/${t}`).then((r) => r.data),
  createTenant: (data: CreateTenantPayload): Promise<CreatedTenant> =>
    api.post('/platform/tenants', data).then((r) => r.data),
  setAgentUrl: (t: string, agent_url: string) =>
    api.put(`/platform/tenants/${t}/agent-url`, { agent_url }).then((r) => r.data),
  /**
   * Cases the tenant's agent holds that this framework has no record of.
   * Read-only; see components/platform/CaseDriftPanel for why this exists.
   */
  caseDrift: (t: string) =>
    api.get(`/platform/tenants/${t}/case-drift`).then((r) => r.data),
  /** Delete agent-side orphans. Ids only — there is no "all" verb on purpose. */
  deleteOrphanCases: (t: string, case_ids: string[]) =>
    api.post(`/platform/tenants/${t}/case-drift/delete`, { case_ids })
      .then((r) => r.data),
  setIdpUrl: (t: string, idp_url: string, backend_secret?: string) =>
    api.put(`/platform/tenants/${t}/idp-url`, { idp_url, backend_secret }).then((r) => r.data),
  setEmailDomains: (t: string, email_domains: string[]) =>
    api.put(`/platform/tenants/${t}/email-domains`, { email_domains }).then((r) => r.data),
  setEnabledModules: (t: string, enabled_modules: string[] | null) =>
    api.put(`/platform/tenants/${t}/enabled-modules`, { enabled_modules }).then((r) => r.data),
  setAiEnabled: (t: string, ai_enabled: boolean) =>
    api.put(`/platform/tenants/${t}/ai-enabled`, { ai_enabled }).then((r) => r.data),
  setSettings: (t: string, data: Partial<TenantSettings>) =>
    api.put(`/platform/tenants/${t}/settings`, data).then((r) => r.data),
  renew: (t: string, valid_days: number) =>
    api.post(`/platform/tenants/${t}/renew`, { valid_days }).then((r) => r.data),
  setActive: (t: string, is_active: boolean) =>
    api.put(`/platform/tenants/${t}/active`, { is_active }).then((r) => r.data),
  deleteTenant: (t: string) => api.delete(`/platform/tenants/${t}`).then((r) => r.data),
  setContacts: (t: string, contacts: Contact[]) =>
    api.put(`/platform/tenants/${t}/contacts`, { contacts }).then((r) => r.data),
  agentHealth: (t: string): Promise<AgentHealth> =>
    api.get(`/platform/tenants/${t}/agent-health`).then((r) => r.data),
  metrics: (): Promise<MetricsSummary> => api.get('/platform/metrics-summary').then((r) => r.data),
  getN8nAccess: (): Promise<{ enabled: boolean }> =>
    api.get('/platform/n8n-access').then((r) => r.data),
  setN8nAccess: (enabled: boolean): Promise<{ enabled: boolean }> =>
    api.put('/platform/n8n-access', { enabled }).then((r) => r.data),
  getN8nVersion: (): Promise<{ current: string | null; latest: string | null; update_available: boolean }> =>
    api.get('/platform/n8n-version').then((r) => r.data),
  getAiSettings: (): Promise<{ max_entities: number }> =>
    api.get('/platform/ai-settings').then((r) => r.data),
  setAiSettings: (max_entities: number): Promise<{ max_entities: number }> =>
    api.put('/platform/ai-settings', { max_entities }).then((r) => r.data),
  getAiUsage: (): Promise<AiUsage> =>
    api.get('/platform/ai-usage').then((r) => r.data),
  resetAiUsage: (): Promise<AiUsage> =>
    api.post('/platform/ai-usage/reset').then((r) => r.data),
  setAiRates: (rate_in_per_m: number, rate_out_per_m: number): Promise<AiUsage> =>
    api.put('/platform/ai-usage/rates', { rate_in_per_m, rate_out_per_m }).then((r) => r.data),
  updateN8n: (): Promise<{ ok: boolean; log: string }> =>
    api.post('/platform/n8n-update').then((r) => r.data),
}

export interface AiUsage {
  runs: number
  prompt_tokens: number
  output_tokens: number
  total_tokens: number
  billable_output_tokens: number
  since: string | null
  last_run: string | null
  last_model: string | null
  rate_in_per_m: number
  rate_out_per_m: number
  estimated_cost_usd: number
  balance_available: boolean
}

// Support tickets / chat between authorities and product owners.
export interface SupportMessage {
  id: string
  author_role: 'tenant' | 'operator'
  author_name: string
  body: string
  created_at: string
}
export interface SupportTicket {
  id: string
  tenant: string
  subject: string
  status: 'open' | 'closed'
  priority: string
  created_by: string
  created_at: string
  updated_at: string
  last_message_at: string
  message_count: number
}
export interface SupportTicketDetail extends SupportTicket {
  messages: SupportMessage[]
}

// Authority (tenant) side — only their own tickets.
export const supportApi = {
  list: (): Promise<SupportTicket[]> => api.get('/support/tickets').then((r) => r.data),
  create: (data: { subject: string; body: string; priority?: string }): Promise<SupportTicket> =>
    api.post('/support/tickets', data).then((r) => r.data),
  get: (id: string): Promise<SupportTicketDetail> => api.get(`/support/tickets/${id}`).then((r) => r.data),
  reply: (id: string, body: string) => api.post(`/support/tickets/${id}/messages`, { body }).then((r) => r.data),
}

// Operator side — all authorities' tickets.
export const platformSupportApi = {
  list: (params?: { status?: string; tenant?: string }): Promise<SupportTicket[]> =>
    api.get('/platform/support/tickets', { params }).then((r) => r.data),
  get: (id: string): Promise<SupportTicketDetail> => api.get(`/platform/support/tickets/${id}`).then((r) => r.data),
  reply: (id: string, body: string) => api.post(`/platform/support/tickets/${id}/messages`, { body }).then((r) => r.data),
  setStatus: (id: string, status: string) => api.put(`/platform/support/tickets/${id}/status`, { status }).then((r) => r.data),
  remove: (id: string) => api.delete(`/platform/support/tickets/${id}`).then((r) => r.data),
}

// Product-owner (operator) account management (platform realm).
export const operatorsApi = {
  list: (): Promise<ProductOwner[]> => api.get('/platform/operators').then((r) => r.data),
  create: (data: { username: string; email?: string; password: string }) =>
    api.post('/platform/operators', data).then((r) => r.data),
  resetPassword: (id: string, password: string) =>
    api.post(`/platform/operators/${id}/reset-password`, { password }).then((r) => r.data),
  remove: (id: string) => api.delete(`/platform/operators/${id}`).then((r) => r.data),
}

// Operator-global OSINT-module API keys (Global-Admin Settings tab).
// The registry is server-driven — new keys appear automatically.
export interface ApiKeyInfo {
  name: string
  label: string
  module: string
  group: string
  register_url: string
  help: string
  secret: boolean
  testable: boolean
  is_set: boolean
  from_env: boolean
  preview: string
}
export interface KeyTestResult { valid: boolean; message: string; account?: string }

export const apiKeysApi = {
  list: (): Promise<ApiKeyInfo[]> => api.get('/platform/api-keys').then((r) => r.data),
  save: (values: Record<string, string>) =>
    api.put('/platform/api-keys', { values }).then((r) => r.data),
  test: (name: string, value?: string): Promise<KeyTestResult> =>
    api.post('/platform/api-keys/test', { name, value: value || '' }).then((r) => r.data),
  testTelegram: (v: { api_id?: string; api_hash?: string; session?: string }): Promise<KeyTestResult> =>
    api.post('/platform/api-keys/test-telegram', v).then((r) => r.data),
  ghuntDerive: (companion: string): Promise<{ ok: boolean; message?: string; master_token?: string; account?: string }> =>
    api.post('/platform/api-keys/ghunt-derive', { companion }).then((r) => r.data),
}

/** One RSS/Atom source searched by module-news. */
export interface NewsFeed {
  id?: string
  name: string
  url: string
  /** authority | police | media | cyber | other — shown in the graph. */
  kind: string
  lang: string
  enabled: boolean
}

export interface FeedTestResult {
  ok: boolean
  status?: number
  entries?: number
  title?: string
  detail?: string
}

export interface NewsSource {
  name: string
  kind: string
  lang: string
  url: string
  enabled: boolean
}

export interface NewsArticle {
  title: string
  url?: string
  summary?: string
  published?: string
  source_name: string
  source_kind: string
  source_lang?: string
  /** Passage in which the search term occurs. */
  match_context?: string
  /** Which of the search terms actually occur in this article. */
  matched_terms?: string[]
  /** Which query variants matched this article (facet fan-out). */
  matched?: string[]
}

/** Analyst-side, read-only news browsing. Nothing is persisted. */
export const newsApi = {
  sources: (): Promise<{ sources: NewsSource[]; configured: boolean }> =>
    api.get('/news/sources').then((r) => r.data),
  search: (query: string, facets: string[] = []): Promise<{
    query: string; count: number; articles: NewsArticle[]; notes: string[]
  }> => api.post('/news/search', { query, facets }).then((r) => r.data),
}

/** AI news analysis — extract entities/connections/summary from the cached
 *  feeds for a keyword. Licensed per authority (ai_enabled), Gemini-backed. */
export interface AiNewsEntity {
  entity_type: string
  label: string
  context?: string
  source_url?: string
  confidence?: number
}
export interface AiNewsConnection {
  from_label: string
  to_label: string
  relation: string
  rationale?: string
  confidence?: number
}
export interface AiNewsResult {
  status: 'running' | 'done' | 'error'
  detail?: string
  query?: string
  articles_analyzed?: number
  summary?: string
  entities?: AiNewsEntity[]
  connections?: AiNewsConnection[]
  case_suggestions?: string[]
}
export const newsAiApi = {
  analyze: (query: string, facets: string[] = [], maxAgeDays?: number):
    Promise<{ job_id: string; status: string }> =>
    api.post('/news/ai-analyze', { query, facets, max_age_days: maxAgeDays })
      .then((r) => r.data),
  status: (jobId: string): Promise<AiNewsResult> =>
    api.get(`/news/ai-analyze/${jobId}`).then((r) => r.data),
  apply: (body: {
    case_id: string
    entities: {
      entity_type: string; label: string
      data?: Record<string, unknown>; confidence?: number; source_url?: string
    }[]
    connections?: {
      from_label: string; to_label: string; relation: string; confidence?: number
    }[]
    keyword?: string
    link_keyword?: boolean
  }): Promise<{ added_entities: number; added_edges: number }> =>
    api.post('/news/ai-apply', body).then((r) => r.data),
}

export interface NewsSettings {
  /** Entries requested per feed — substituted for {{max}} in feed URLs. */
  max_entries_per_feed: number
  /** Hits returned to the analyst per search. */
  max_results: number
  /** Ignore entries older than this many days. 0 = no limit. */
  max_age_days: number
}

/** Per-feed fetch health, gathered from real searches (not the Test button). */
export interface FeedHealth {
  last_ok?: number | null
  last_error?: number | null
  error?: string | null
  fails?: number
  entries?: number | null
  /** Set while an outage is ongoing; cleared by the next success. */
  failing_since?: number | null
}

export const newsFeedsApi = {
  list: (): Promise<{
    feeds: NewsFeed[]; kinds: string[]; settings: NewsSettings
    max_placeholder: string; health: Record<string, FeedHealth>
  }> =>
    api.get('/platform/news-feeds').then((r) => r.data),
  save: (feeds: NewsFeed[]): Promise<{ feeds: NewsFeed[] }> =>
    api.put('/platform/news-feeds', { feeds }).then((r) => r.data),
  test: (url: string): Promise<FeedTestResult> =>
    api.post('/platform/news-feeds/test', { url }).then((r) => r.data),
  saveSettings: (s: NewsSettings): Promise<{ settings: NewsSettings }> =>
    api.put('/platform/news-settings', s).then((r) => r.data),
}

export interface TgChannel {
  id: string
  handle: string
  category: string
  note: string
  source: string
  /** Marks the subset that is actually swept by every username search. */
  enabled: boolean
  /** "" = never checked, which is not the same as "checked and fine". */
  status: string
  checked_at: string
  title: string
  subscribers: string
  /** Parsed audience size; 0 when unknown. */
  reach: number
}

/**
 * Operator-maintained Telegram channel pool for the username sweep.
 *
 * The pool can hold ~1000 handles; only `enabled` ones cost search time,
 * and the module still caps them at `sweep_cap`. That split is the whole
 * point — importing everything as active would make every username search
 * hopeless and then silently truncate.
 */
export const telegramChannelsApi = {
  list: (): Promise<{
    channels: TgChannel[]; total: number; enabled: number
    categories: Record<string, number>; sources: string[]; sweep_cap: number
  }> => api.get('/platform/telegram-channels').then((r) => r.data),
  save: (channels: TgChannel[]) =>
    api.put('/platform/telegram-channels', { channels }).then((r) => r.data),
  /** Paste handles / @handles / t.me URLs — one per line or comma separated. */
  bulk: (text: string, category: string, enabled: boolean) =>
    api.post('/platform/telegram-channels/bulk', { text, category, enabled })
      .then((r) => r.data),
  /** Refresh the pool from deepdarkCTI. Imports arrive disabled. */
  import: (files?: string[]) =>
    api.post('/platform/telegram-channels/import', { files: files || [] })
      .then((r) => r.data),
  /** Probe t.me for liveness. Keyless — never resolves through the account. */
  check: (only_enabled: boolean, limit = 200) =>
    api.post('/platform/telegram-channels/check', { only_enabled, limit })
      .then((r) => r.data),
  /**
   * Act on channels that showed no public page. Defaults to DISABLE:
   * an invite-only channel probes identically to a deleted one, so
   * deleting on that signal alone throws away valid targets.
   */
  cleanup: (remove: boolean, only_enabled: boolean) =>
    api.post('/platform/telegram-channels/cleanup', { remove, only_enabled })
      .then((r) => r.data),
}

export interface TgSource {
  id: string
  url: string
  /** github_repo = every .md in the repo is scanned; url = that one file. */
  kind: string
  category: string
  enabled: boolean
  last_run: string
  last_found: number
  last_added: number
  last_error: string
}

/** Operator-defined harvest sources — GitHub repos or raw list URLs. */
export const telegramSourcesApi = {
  list: (): Promise<{ sources: TgSource[] }> =>
    api.get('/platform/telegram-sources').then((r) => r.data),
  save: (sources: TgSource[]) =>
    api.put('/platform/telegram-sources', { sources }).then((r) => r.data),
  scan: (source_id?: string) =>
    api.post('/platform/telegram-sources/scan', { source_id: source_id || null })
      .then((r) => r.data),
}

export interface ProbeHistory {
  probes: number
  answered: number
  rate: number | null
  last: string
}

export interface CrimeForum {
  id: string
  domain: string
  category: string
  note: string
  source: string
  /** Marks the subset that is actually dorked by every forum hunt. */
  enabled: boolean
  /**
   * Which half of the tool can use this entry. `clearnet` entries are
   * dorked through a search engine and cost one query per hunt; `onion`
   * entries are never fetched by the hunt — they are the recognition table
   * that lets the Tor sweep name a hit instead of reporting an anonymous
   * hidden service. Derived from the host, never set by the client.
   */
  surface: 'clearnet' | 'onion'
  /** Human-readable forum name from the source list, e.g. "BreachForums". */
  name: string
  /**
   * Probe HISTORY for the two probes that touch the host, derived server-side
   * from a bounded log of past outcomes. `rate` is null when the host was
   * never probed — deliberately not 0.0, because "never asked" and "asked ten
   * times, never answered" are different facts about a forum.
   */
  reach_history?: ProbeHistory
  access_history?: ProbeHistory
  /**
   * Health check. "" everywhere = never checked, which is not the same as
   * "checked and fine".
   *
   * `index_status` is the decisive one — the hunt asks a search engine and
   * never fetches the forum, so an un-indexed forum yields nothing however
   * alive it is. `reach_status` is context: it separates dead from
   * alive-but-closed, and `blocked` specifically means the host answered
   * and refused us.
   */
  index_status: '' | 'indexed' | 'not_indexed' | 'no_key' | 'error'
  index_count: number
  reach_status: '' | 'online' | 'blocked' | 'unreachable' | 'no_tor' | 'error'
  reach_note: string
  title: string
  checked_at: string
  /**
   * Can a GUEST read this forum's member area — the probe that decides what
   * is buildable per forum at all. `index_status` says what a search engine
   * got from the outside; this says what we can read directly, as nobody.
   *
   * `login_required` is a FINDING, not a to-do: giving the framework an
   * account is a decision with a legal shape (covert investigation rules,
   * and operator containers actively retrieving forum content), not a
   * configuration step.
   */
  access_status: '' | 'guest_open' | 'login_required' | 'blocked'
    | 'unreachable' | 'unknown' | 'no_tor'
  access_note: string
  /** Detected forum software, e.g. `mybb`, `phpbb`, `xenforo`. */
  software: string
  /**
   * Only set for software that addresses a profile by NAME. XenForo, SMF and
   * vBulletin key profiles on a numeric id, so a per-handle account check can
   * never work there — an empty template is that statement, not a gap.
   */
  profile_template: string
}

/**
 * Operator-maintained crime-forum list for `forums/crime_forum_hunt`.
 *
 * Same shape as the Telegram channel pool, and for the same reason: the
 * hunt spends one search-engine query PER ENABLED forum, so the enabled
 * count — not the pool size — is what a search costs. Crime forums are
 * seized and reborn under new domains several times a year, which is why
 * this is a console list rather than a container env var.
 */
export const crimeForumsApi = {
  list: (): Promise<{
    forums: CrimeForum[]; total: number; enabled: number
    categories: Record<string, number>; available_categories: string[]
    hunt_cap: number; defaults_count: number
    /** Split by surface — only the clearnet half costs query budget. */
    clearnet: number; onion: number; enabled_clearnet: number
    /** Entries whose access probe has never produced a verdict. */
    inconclusive_access: number; probe_log_len: number
  }> => api.get('/platform/crime-forums').then((r) => r.data),
  save: (forums: CrimeForum[]) =>
    api.put('/platform/crime-forums', { forums }).then((r) => r.data),
  /** Paste domains or URLs — one per line or comma separated. */
  bulk: (text: string, category: string, enabled: boolean) =>
    api.post('/platform/crime-forums/bulk', { text, category, enabled })
      .then((r) => r.data),
  /**
   * Fold deepdarkCTI's forum.md in. Arrives DISABLED — that file yields
   * ~187 clearnet hosts against a per-hunt cap of 40, so importing active
   * would slow every hunt and then truncate silently. Onion entries come in
   * as the recognition table.
   */
  importDdcti: () =>
    api.post('/platform/crime-forums/import', {}).then((r) => r.data),
  /** Fold the module's built-in list in. Stored entries keep their settings. */
  defaults: (enabled = true) =>
    api.post('/platform/crime-forums/defaults', { enabled }).then((r) => r.data),
  /**
   * `index` (default) measures search-engine coverage without contacting
   * the forum; `reach` probes the host over Tor; `access` asks whether a
   * guest can read the member area and fingerprints the forum software;
   * `both` runs index + reach.
   *
   * Every mode probes NEVER-CHECKED entries first and reports `remaining`,
   * so a pool larger than one batch converges over repeated runs instead of
   * re-measuring the same head of the list. `access` batches at 50, not 200:
   * it makes two Tor requests per host.
   *
   * `recheck` flips that rule: it re-probes entries whose last host-touching
   * answer was INCONCLUSIVE (unreachable / unknown), fewest probes first.
   * Both passes are needed and they converge on different things — the first
   * on coverage, the second on a REPEATED measurement, and only a repeated
   * one separates a dropped Tor circuit from a board that is actually gone.
   */
  check: (mode: 'index' | 'reach' | 'access' | 'both', recheck = false,
          only_enabled = false, limit = 200) =>
    api.post('/platform/crime-forums/check',
             { mode, recheck, only_enabled, limit })
      .then((r) => r.data),
  /**
   * Act on forums the index probe found nothing for. Defaults to DISABLE:
   * a forum can drop out of an index and come back, and a switched-off
   * entry costs nothing.
   */
  cleanup: (remove = false) =>
    api.post('/platform/crime-forums/cleanup', { remove }).then((r) => r.data),
}

export interface ForumIndexInfo {
  index_mtime?: string | null
  age_days?: number | null
  active_index?: string | null
  /** True while the copy baked into the image is in use — i.e. the volume
   *  copy has never been written and no refresh has ever completed. */
  using_baked_seed?: boolean
  state?: string
  last_error?: string | null
  /** Rows in the index: handles for `threat_actors`, boards for `linkbase`. */
  entries?: number | null
  /**
   * How many forums this dataset COVERS — deliberately not the operator's
   * dork list, which lives in the same console tab and is a different set
   * entirely (they overlap, they are not the same).
   */
  forums?: number | null
  dead_forums?: number | null
  running?: boolean
  due?: boolean
  error?: string
}

/**
 * The two reference indexes inside module-forums: ~830k crime-forum handles
 * and the link-base directory. Content-independent lookup data with no case
 * link — case findings live on the customer's agent, never here.
 */
export const forumIndexesApi = {
  status: (): Promise<{
    indexes: Record<string, ForumIndexInfo>
    reachable: boolean
    refresh_days: number
  }> => api.get('/platform/forum-indexes').then((r) => r.data),
  refresh: (index: string) =>
    api.post('/platform/forum-indexes/refresh', { index }).then((r) => r.data),
}

/** Background RSS-harvester schedule (authority vs. other interval, on/off). */
export interface HarvestSettings {
  enabled: boolean
  authority_interval_min: number
  other_interval_min: number
}

export interface HarvesterStatus {
  settings: HarvestSettings
  stats: {
    total_articles: number
    per_kind: { kind: string; count: number }[]
    feeds_enabled: number
    feeds_due: number
    newest_published: string | null
    /** Unix seconds of the most recent stored article. */
    last_harvest: number | null
  }
  /**
   * Disk footprint of the news cache, straight from Postgres.
   *
   * This is the one table in the system with **no retention rule** — cases
   * are purged daily, this grows forever by design (an article deleted
   * after 90 days is one an analyst can no longer cite). Hence the
   * projection: the growth has to be visible before the disk decides.
   */
  storage: {
    bytes: number
    rows: number
    bytes_per_article: number
    per_table: { table: string; bytes: number; heap_bytes: number; index_bytes: number }[]
    added_7d: number
    added_30d: number
    /** null until at least one full day has been observed. */
    projected_bytes_per_month: number | null
    /** How long that projection actually watched — 2 days is not 30. */
    observed_days: number
    oldest_fetch: number | null
    /** Always null today: there is no retention policy. */
    retention_days: number | null
  }
  feeds: {
    feed_id?: string
    name?: string
    kind?: string
    interval_min: number
    last_poll_ok?: number | null
    last_entry_count?: number | null
    consecutive_fails: number
    last_error?: string | null
    due: boolean
  }[]
}

export const newsHarvesterApi = {
  get: (): Promise<HarvesterStatus> =>
    api.get('/platform/news-harvester').then((r) => r.data),
  saveSettings: (s: Partial<HarvestSettings>): Promise<{ settings: HarvestSettings }> =>
    api.put('/platform/news-harvester', s).then((r) => r.data),
  run: (): Promise<{ status: string; summary: Record<string, number> }> =>
    api.post('/platform/news-harvester/run').then((r) => r.data),
}

// PDF reports. Section list comes from the backend so
// the frontend doesn't have to know which sections exist; new ones
// dropped into backend/app/services/report/sections/ appear here.
export interface ReportSection {
  name: string
  order: number
  default: boolean
}

export const reportApi = {
  listSections: (): Promise<ReportSection[]> =>
    api.get('/report/sections').then((r) => r.data),
  generate: (caseId: string, sections: string[] | null, lang: string,
             opts: { only_relevant?: boolean; format?: 'pdf' | 'docx' } = {}): Promise<Blob> =>
    api.post(
      `/cases/${caseId}/report`,
      { sections, lang, ...opts },
      { responseType: 'blob' },
    ).then((r) => r.data),
}

export interface EvidenceItem {
  id: string
  case_id: string
  entity_id: string | null
  url: string
  final_url: string | null
  http_status: number | null
  title: string | null
  captured_at: string
  captured_by: string | null
  via_tor: boolean
  user_agent: string | null
  screenshot_sha256: string
  archive_sha256: string
  archive_type: string
  meta: { redirect_chain?: string[]; blocked_requests?: string[]; screenshot_truncated?: boolean
          screenshot_bytes?: number; archive_bytes?: number; [k: string]: any }
}

/** Saved pages (screenshot + MHTML + SHA-256). Stored in the customer's own
 *  database; a capture can take over a minute for an onion page. */
export const evidenceApi = {
  capture: (caseId: string, body: { entity_id?: string; url?: string }): Promise<EvidenceItem> =>
    api.post(`/cases/${caseId}/evidence`, body, { timeout: 140000 }).then((r) => r.data),
  list: (caseId: string): Promise<{ evidence: EvidenceItem[] }> =>
    api.get(`/cases/${caseId}/evidence`).then((r) => r.data),
  file: (caseId: string, id: string, kind: 'screenshot' | 'archive'): Promise<Blob> =>
    api.get(`/cases/${caseId}/evidence/${id}/${kind}`, { responseType: 'blob' }).then((r) => r.data),
}

export const exportApi = {
  /** CSV / Maltego CSV / MISP event / STIX 2.1 bundle. */
  download: (caseId: string, format: string): Promise<Blob> =>
    api.get(`/cases/${caseId}/export`, { params: { format }, responseType: 'blob' })
      .then((r) => r.data),
}

export const monitoringApi = {
  list: () => api.get('/monitoring').then((r) => r.data),
  get: (id: string) => api.get(`/monitoring/${id}`).then((r) => r.data),
  create: (data: object) => api.post('/monitoring', data).then((r) => r.data),
  update: (id: string, data: object) => api.put(`/monitoring/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/monitoring/${id}`).then((r) => r.data),
}

export default api
