import { onUnmounted, ref, watch, type Ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
// How often lines are fetched while what they come from runs - the workers send theirs every 2 s.
const POLL_MS = 2000
// Pages fetched in a row when far behind, before waiting for the next poll.
const MAX_PAGES_PER_POLL = 10

export interface TaskLogEntry {
  id: number
  taskName: string
  ts: string
  level: string
  message: string
}

interface TaskLogEntryOut {
  id: number
  task_name: string
  ts: string
  level: string
  message: string
}

interface TaskLogsOut {
  entries: TaskLogEntryOut[]
  has_more: boolean
}

/**
 * The log lines of a task or of a document (#305), as the workers send them: only those after the last
 * one already read are fetched (`after`), every POLL_MS while `live`. `path` is the API path, e.g.
 * `/api/tasks/<id>/logs`; `level` keeps the lines of that level and above, '' all of them.
 */
export function useTaskLogs(path: Ref<string>, live: Ref<boolean>, level: Ref<string>) {
  const entries = ref<TaskLogEntry[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  let lastId = 0
  // A response to a request made before a reset (another level, another path) is dropped.
  let generation = 0
  let inFlight = false

  async function fetchNew() {
    if (inFlight) return
    inFlight = true
    const current = generation
    try {
      for (let page = 0; page < MAX_PAGES_PER_POLL; page++) {
        const params = new URLSearchParams({ after: String(lastId) })
        if (level.value) params.set('level', level.value)
        const response = await fetch(`${API_BASE_URL}${path.value}?${params}`, { credentials: 'include' })
        if (!response.ok) throw new Error(`${response.status}`)
        const body: TaskLogsOut = await response.json()
        if (current !== generation) return
        error.value = null
        if (body.entries.length) {
          entries.value.push(
            ...body.entries.map((entry) => ({
              id: entry.id,
              taskName: entry.task_name,
              ts: entry.ts,
              level: entry.level,
              message: entry.message,
            })),
          )
          lastId = body.entries[body.entries.length - 1].id
        }
        if (!body.has_more) break
      }
    } catch {
      if (current === generation) error.value = 'Impossible de récupérer les logs.'
    } finally {
      if (current === generation) inFlight = false
    }
  }

  async function reset() {
    generation++
    inFlight = false
    entries.value = []
    lastId = 0
    isLoading.value = true
    await fetchNew()
    isLoading.value = false
  }

  let timer: ReturnType<typeof setInterval> | undefined
  function stopPolling() {
    if (timer !== undefined) clearInterval(timer)
    timer = undefined
  }

  watch([path, level], reset, { immediate: true })
  watch(
    live,
    (isLive) => {
      stopPolling()
      if (isLive) timer = setInterval(fetchNew, POLL_MS)
      // Just ended: the last lines, sent as it ended.
      else void fetchNew()
    },
    { immediate: true },
  )
  onUnmounted(stopPolling)

  return { entries, isLoading, error }
}
