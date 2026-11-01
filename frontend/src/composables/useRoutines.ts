import { ref } from 'vue'
import type {
  AdminRoutine,
  Routine,
  RoutineDraft,
  RoutineRun,
  RoutineSchedule,
  RoutineSettings,
  RoutineStatus,
} from '../types/routine'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface ScheduleOut {
  kind: RoutineSchedule['kind']
  timezone: string
  interval_minutes: number | null
  time_of_day: string | null
  weekdays: number[] | null
  day_of_month: number | null
}

interface RunOut {
  id: string
  status: RoutineRun['status']
  skip_reason: string | null
  trigger: RoutineRun['trigger']
  error: string | null
  note: string | null
  total_tokens: number
  conversation_id: string | null
  started_at: string
  finished_at: string | null
  duration_seconds: number | null
}

interface RoutineOut {
  id: string
  name: string
  question: string
  collection_ids: string[]
  include_descendants: boolean
  assistant_id: string | null
  web_search: boolean
  schedule: ScheduleOut
  condition: Routine['condition']
  result_mode: Routine['resultMode']
  notify: Routine['notify']
  state: Routine['state']
  suspended_reason: string | null
  next_run_at: string | null
  last_run_at: string | null
  consecutive_failures: number
  conversation_id: string | null
  last_run: RunOut | null
  created_at: string
}

function toSchedule(raw: ScheduleOut): RoutineSchedule {
  return {
    kind: raw.kind,
    timezone: raw.timezone,
    intervalMinutes: raw.interval_minutes,
    timeOfDay: raw.time_of_day ? raw.time_of_day.slice(0, 5) : null,
    weekdays: raw.weekdays,
    dayOfMonth: raw.day_of_month,
  }
}

function fromSchedule(schedule: RoutineSchedule): ScheduleOut {
  return {
    kind: schedule.kind,
    timezone: schedule.timezone,
    interval_minutes: schedule.kind === 'interval' ? schedule.intervalMinutes : null,
    time_of_day: schedule.kind === 'interval' ? null : schedule.timeOfDay,
    weekdays: schedule.kind === 'weekly' ? schedule.weekdays : null,
    day_of_month: schedule.kind === 'monthly' ? schedule.dayOfMonth : null,
  }
}

function toRun(raw: RunOut): RoutineRun {
  return {
    id: raw.id,
    status: raw.status,
    skipReason: raw.skip_reason,
    trigger: raw.trigger,
    error: raw.error,
    note: raw.note,
    totalTokens: raw.total_tokens,
    conversationId: raw.conversation_id,
    startedAt: raw.started_at,
    finishedAt: raw.finished_at,
    durationSeconds: raw.duration_seconds,
  }
}

function toRoutine(raw: RoutineOut): Routine {
  return {
    id: raw.id,
    name: raw.name,
    question: raw.question,
    collectionIds: raw.collection_ids,
    includeDescendants: raw.include_descendants,
    assistantId: raw.assistant_id,
    webSearch: raw.web_search,
    schedule: toSchedule(raw.schedule),
    condition: raw.condition,
    resultMode: raw.result_mode,
    notify: raw.notify,
    state: raw.state,
    suspendedReason: raw.suspended_reason,
    nextRunAt: raw.next_run_at,
    lastRunAt: raw.last_run_at,
    consecutiveFailures: raw.consecutive_failures,
    conversationId: raw.conversation_id,
    lastRun: raw.last_run ? toRun(raw.last_run) : null,
    createdAt: raw.created_at,
  }
}

function toBody(draft: RoutineDraft) {
  return {
    name: draft.name.trim(),
    question: draft.question.trim(),
    collection_ids: draft.collectionIds,
    include_descendants: draft.includeDescendants,
    assistant_id: draft.assistantId,
    web_search: draft.webSearch,
    schedule: fromSchedule(draft.schedule),
    condition: draft.condition,
    result_mode: draft.resultMode,
    notify: draft.notify,
  }
}

// Ce que dit l'API quand elle refuse : une phrase de l'application (code stable, mots pour la personne).
async function refusal(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
    if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === 'string') return body.detail[0].msg
  } catch {
    // Pas de corps à lire.
  }
  return fallback
}

// Module-level singleton : la liste, le formulaire et l'historique voient les mêmes routines.
const routines = ref<Routine[]>([])
const status = ref<RoutineStatus | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function loadStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/routines/status`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const raw = await response.json()
    status.value = {
      enabled: raw.enabled,
      maxActive: raw.max_active,
      minIntervalMinutes: raw.min_interval_minutes,
      maxRunsPerDay: raw.max_runs_per_day,
      active: raw.active,
      runsToday: raw.runs_today,
    }
  } catch {
    error.value = 'Impossible de récupérer l’état des routines.'
  }
}

async function loadRoutines() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/routines`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    routines.value = (await response.json()).map(toRoutine)
  } catch {
    error.value = 'Impossible de récupérer vos routines.'
  } finally {
    isLoading.value = false
  }
  await loadStatus()
}

async function send(path: string, method: string, body?: unknown): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/routines${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

// Les actions rendent la routine à jour, ou le message du refus : `null` pour réussi, le texte sinon.
async function save(draft: RoutineDraft, id?: string): Promise<string | null> {
  const response = await send(id ? `/${id}` : '', id ? 'PATCH' : 'POST', {
    ...toBody(draft),
    ...(id && !draft.assistantId ? { clear_assistant: true, assistant_id: null } : {}),
  })
  if (!response.ok) return refusal(response, 'Impossible d’enregistrer la routine.')
  await loadRoutines()
  return null
}

async function act(id: string, action: 'pause' | 'resume', fallback: string): Promise<string | null> {
  const response = await send(`/${id}/${action}`, 'POST')
  if (!response.ok) return refusal(response, fallback)
  await loadRoutines()
  return null
}

const pause = (id: string) => act(id, 'pause', 'Impossible de mettre la routine en pause.')
const resume = (id: string) => act(id, 'resume', 'Impossible de reprendre la routine.')

async function remove(id: string): Promise<string | null> {
  const response = await send(`/${id}`, 'DELETE')
  if (!response.ok) return refusal(response, 'Impossible de supprimer la routine.')
  routines.value = routines.value.filter((routine) => routine.id !== id)
  await loadStatus()
  return null
}

// Essaie la routine sans attendre sa date : rend l'exécution (qui peut avoir été sautée, avec son motif).
async function runNow(id: string): Promise<{ run: RoutineRun | null; message: string | null }> {
  const response = await send(`/${id}/run`, 'POST')
  if (!response.ok) return { run: null, message: await refusal(response, 'Impossible de lancer la routine.') }
  const run = toRun((await response.json()).run)
  await loadRoutines()
  return { run, message: null }
}

async function loadRuns(id: string, page = 1): Promise<{ items: RoutineRun[]; total: number } | null> {
  try {
    const response = await send(`/${id}/runs?page=${page}&page_size=20`, 'GET')
    if (!response.ok) return null
    const body = await response.json()
    return { items: body.items.map(toRun), total: body.total }
  } catch {
    return null
  }
}

// Les prochaines dates d'un rythme, pour le vérifier avant de le garder ; `message` quand il est refusé.
async function preview(schedule: RoutineSchedule): Promise<{ dates: string[]; message: string | null }> {
  try {
    const response = await send('/preview', 'POST', fromSchedule(schedule))
    if (!response.ok) return { dates: [], message: await refusal(response, 'Rythme invalide.') }
    return { dates: (await response.json()).dates, message: null }
  } catch {
    return { dates: [], message: 'Le serveur est inaccessible.' }
  }
}

export function useRoutines() {
  return { routines, status, isLoading, error, loadRoutines, loadStatus, save, pause, resume, remove, runNow, loadRuns, preview }
}

// --- Administration ---

interface AdminRoutineOut {
  id: string
  name: string
  owner_display: string
  schedule: ScheduleOut
  state: Routine['state']
  suspended_reason: string | null
  next_run_at: string | null
  last_run_at: string | null
  consecutive_failures: number
  last_status: RoutineRun['status'] | null
  tokens_30_days: number
}

interface SettingsOut {
  enabled: boolean
  max_active_per_user: number
  min_interval_minutes: number
  max_runs_per_user_per_day: number
  max_concurrent: number
  max_consecutive_failures: number
  inactive_days: number
  run_timeout_minutes: number
}

const settings = ref<RoutineSettings | null>(null)
const adminRoutines = ref<AdminRoutine[]>([])
const adminTotal = ref(0)
const adminError = ref<string | null>(null)

function toSettings(raw: SettingsOut): RoutineSettings {
  return {
    enabled: raw.enabled,
    maxActivePerUser: raw.max_active_per_user,
    minIntervalMinutes: raw.min_interval_minutes,
    maxRunsPerUserPerDay: raw.max_runs_per_user_per_day,
    maxConcurrent: raw.max_concurrent,
    maxConsecutiveFailures: raw.max_consecutive_failures,
    inactiveDays: raw.inactive_days,
    runTimeoutMinutes: raw.run_timeout_minutes,
  }
}

async function loadAdmin(page = 1) {
  adminError.value = null
  try {
    const [settingsResponse, listResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/admin/routines/settings`, { credentials: 'include' }),
      fetch(`${API_BASE_URL}/api/admin/routines?page=${page}&page_size=50`, { credentials: 'include' }),
    ])
    if (!settingsResponse.ok || !listResponse.ok) throw new Error('refused')
    settings.value = toSettings(await settingsResponse.json())
    const list = await listResponse.json()
    adminTotal.value = list.total
    adminRoutines.value = list.items.map((raw: AdminRoutineOut) => ({
      id: raw.id,
      name: raw.name,
      ownerDisplay: raw.owner_display,
      schedule: toSchedule(raw.schedule),
      state: raw.state,
      suspendedReason: raw.suspended_reason,
      nextRunAt: raw.next_run_at,
      lastRunAt: raw.last_run_at,
      consecutiveFailures: raw.consecutive_failures,
      lastStatus: raw.last_status,
      tokens30Days: raw.tokens_30_days,
    }))
  } catch {
    adminError.value = 'Impossible de récupérer les routines.'
  }
}

async function saveSettings(draft: RoutineSettings): Promise<string | null> {
  const response = await fetch(`${API_BASE_URL}/api/admin/routines/settings`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled: draft.enabled,
      max_active_per_user: draft.maxActivePerUser,
      min_interval_minutes: draft.minIntervalMinutes,
      max_runs_per_user_per_day: draft.maxRunsPerUserPerDay,
      max_concurrent: draft.maxConcurrent,
      max_consecutive_failures: draft.maxConsecutiveFailures,
      inactive_days: draft.inactiveDays,
      run_timeout_minutes: draft.runTimeoutMinutes,
    }),
  })
  if (!response.ok) return refusal(response, 'Impossible d’enregistrer les réglages.')
  settings.value = toSettings(await response.json())
  return null
}

async function adminAct(id: string, action: 'suspend' | 'release'): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/api/admin/routines/${id}/${action}`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!response.ok) return false
  await loadAdmin()
  return true
}

export function useAdminRoutines() {
  return {
    settings,
    routines: adminRoutines,
    total: adminTotal,
    error: adminError,
    load: loadAdmin,
    saveSettings,
    suspend: (id: string) => adminAct(id, 'suspend'),
    release: (id: string) => adminAct(id, 'release'),
  }
}
