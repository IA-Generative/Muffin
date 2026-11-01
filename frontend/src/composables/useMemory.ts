import { ref } from 'vue'
import type { MemoryItem, MemoryKind, MemoryState } from '../types/memory'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface MemoryItemOut {
  id: string
  kind: MemoryKind
  value: string
  origin: MemoryItem['origin']
  enabled: boolean
  updated_at: string
  last_used_at: string | null
}

interface MemoryOut {
  enabled: boolean
  available: boolean
  max_items: number
  value_max_chars: number
  items: MemoryItemOut[]
}

function toItem(raw: MemoryItemOut): MemoryItem {
  return {
    id: raw.id,
    kind: raw.kind,
    value: raw.value,
    origin: raw.origin,
    enabled: raw.enabled,
    updatedAt: raw.updated_at,
    lastUsedAt: raw.last_used_at,
  }
}

function toState(raw: MemoryOut): MemoryState {
  return {
    enabled: raw.enabled,
    available: raw.available,
    maxItems: raw.max_items,
    valueMaxChars: raw.value_max_chars,
    items: raw.items.map(toItem),
  }
}

async function refusal(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
  } catch {
    // Pas de corps à lire.
  }
  return fallback
}

const memory = ref<MemoryState | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
// La mémoire sert-elle dans la conversation en cours ? Se coupe depuis « + » : une conversation sans mémoire ne lit rien
// de ce qui est retenu, et n'y ajoute rien. Reste comme réglé d'un message à l'autre, comme la recherche web.
const memoryInChat = ref(true)

function call(path: string, method = 'GET', body?: unknown): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/memory${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

async function load() {
  isLoading.value = true
  error.value = null
  try {
    const response = await call('')
    if (!response.ok) throw new Error('refused')
    memory.value = toState(await response.json())
  } catch {
    error.value = 'Impossible de récupérer votre mémoire.'
  } finally {
    isLoading.value = false
  }
}

// `null` quand c'est fait, le message du refus sinon.
async function add(kind: MemoryKind, value: string): Promise<string | null> {
  const response = await call('/items', 'POST', { kind, value })
  if (!response.ok) return refusal(response, 'Impossible de retenir cela.')
  await load()
  return null
}

async function change(id: string, changes: { value?: string; enabled?: boolean }): Promise<string | null> {
  const response = await call(`/items/${id}`, 'PATCH', changes)
  if (!response.ok) return refusal(response, 'Impossible de modifier cet élément.')
  await load()
  return null
}

async function remove(id: string): Promise<string | null> {
  const response = await call(`/items/${id}`, 'DELETE')
  if (!response.ok) return refusal(response, 'Impossible de supprimer cet élément.')
  await load()
  return null
}

async function removeAll(): Promise<string | null> {
  const response = await call('/items', 'DELETE')
  if (!response.ok) return refusal(response, 'Impossible de tout supprimer.')
  await load()
  return null
}

async function setEnabled(enabled: boolean): Promise<string | null> {
  const response = await call('/settings', 'PUT', { enabled })
  if (!response.ok) return refusal(response, 'Impossible de changer ce réglage.')
  memory.value = toState(await response.json())
  return null
}

// Tout ce qui est retenu, tel que le serveur le donne : un fichier JSON à télécharger.
async function exportAll(): Promise<string | null> {
  const response = await call('/export')
  if (!response.ok) return refusal(response, 'Impossible d’exporter votre mémoire.')
  const blob = new Blob([JSON.stringify(await response.json(), null, 2)], { type: 'application/json' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = 'ma-memoire.json'
  link.click()
  URL.revokeObjectURL(link.href)
  return null
}

export function useMemory() {
  return { memory, isLoading, error, memoryInChat, load, add, change, remove, removeAll, setEnabled, exportAll }
}
