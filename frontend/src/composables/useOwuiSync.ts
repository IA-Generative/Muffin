import { onBeforeUnmount, ref } from 'vue'
import type { OwuiSyncAccount, OwuiSyncRun, SyncedCollection } from '../types/owuiSync'

// Same origin rule as useCollections: the BFF session cookie is scoped to the backend's origin.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface CountsOut {
  seen: number
  errors: number
  dropped: number
  unlisted?: number
  inconsistent?: number
}

interface RunOut {
  run_id: string
  status: OwuiSyncRun['status']
  started_at: string
  finished_at: string | null
  account: { groups?: CountsOut; knowledge_bases?: CountsOut; files?: CountsOut } | null
  error: string | null
  stalled: boolean
  with_problems: boolean
}

interface StateOut {
  latest: RunOut | null
  running: boolean
}

interface SyncedCollectionOut {
  id: string
  name: string
  external_id: string
  state: SyncedCollection['state']
  document_count: number
  summary_count: number
  synced_at: string | null
  problems: string[]
}

function toAccount(raw: RunOut['account']): OwuiSyncAccount | null {
  if (!raw) return null
  return { groups: raw.groups, knowledgeBases: raw.knowledge_bases, files: raw.files }
}

function toRun(raw: RunOut): OwuiSyncRun {
  return {
    runId: raw.run_id,
    status: raw.status,
    startedAt: raw.started_at,
    finishedAt: raw.finished_at,
    account: toAccount(raw.account),
    error: raw.error,
    stalled: raw.stalled,
    withProblems: raw.with_problems,
  }
}

function toCollection(raw: SyncedCollectionOut): SyncedCollection {
  return {
    id: raw.id,
    name: raw.name,
    externalId: raw.external_id,
    state: raw.state,
    documentCount: raw.document_count,
    summaryCount: raw.summary_count,
    syncedAt: raw.synced_at,
    problems: raw.problems,
  }
}

const POLL_MS = 3000

// The page of the administrators for the synchronisation with Open WebUI (#466): the latest run, the copied collections,
// and a button that starts one. While one runs, the page asks again every few seconds.
export function useOwuiSync() {
  const latest = ref<OwuiSyncRun | null>(null)
  const running = ref(false)
  const collections = ref<SyncedCollection[]>([])
  const isLoading = ref(true)
  const error = ref<string | null>(null)
  const isStarting = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  async function get(path: string): Promise<Response | null> {
    try {
      return await fetch(`${API_BASE_URL}/api/admin/owui-sync${path}`, { credentials: 'include' })
    } catch {
      error.value = 'Le serveur est inaccessible.'
      return null
    }
  }

  async function refresh() {
    const [state, list] = await Promise.all([get(''), get('/collections')])
    if (state?.ok) {
      const body: StateOut = await state.json()
      latest.value = body.latest ? toRun(body.latest) : null
      running.value = body.running
      error.value = null
    } else if (state) {
      error.value = state.status === 403 ? 'Réservé aux administrateurs.' : `Échec du chargement (${state.status}).`
    }
    if (list?.ok) collections.value = ((await list.json()) as SyncedCollectionOut[]).map(toCollection)
    isLoading.value = false
    schedule()
  }

  function schedule() {
    if (timer) clearTimeout(timer)
    timer = running.value || isStarting.value ? setTimeout(refresh, POLL_MS) : null
  }

  async function start() {
    isStarting.value = true
    error.value = null
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/owui-sync`, { method: 'POST', credentials: 'include' })
      if (!response.ok) error.value = `Échec du lancement (${response.status}).`
    } catch {
      error.value = 'Échec du lancement : le serveur est inaccessible.'
    }
    // The run shows up when the worker reports it, a few seconds later: ask again until it does.
    const before = latest.value?.runId ?? null
    for (let attempt = 0; attempt < 10 && !error.value; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await refresh()
      if (latest.value?.runId !== before) break
    }
    isStarting.value = false
    schedule()
  }

  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })

  return { latest, running, collections, isLoading, error, isStarting, refresh, start }
}
