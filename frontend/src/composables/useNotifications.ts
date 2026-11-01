import { computed, ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
// Le compteur de la cloche est relevé à l'ouverture, puis toutes les heures ; un flux en direct pourra prendre le relais.
const COUNT_EVERY_MS = 60 * 60 * 1000
const PAGE_SIZE = 20

export interface AppNotification {
  id: string
  type: string
  title: string
  summary: string
  // Un chemin de l'application, jamais l'adresse d'un autre site.
  link: string | null
  read: boolean
  createdAt: string
}

export interface NotificationPreference {
  type: string
  label: string
  description: string
  app: boolean
}

interface NotificationOut {
  id: string
  type: string
  title: string
  summary: string
  link: string | null
  read: boolean
  created_at: string
}

interface PageOut {
  items: NotificationOut[]
  next_cursor: string | null
  unread: number
}

function toNotification(raw: NotificationOut): AppNotification {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    summary: raw.summary,
    link: raw.link && raw.link.startsWith('/') && !raw.link.startsWith('//') ? raw.link : null,
    read: raw.read,
    createdAt: raw.created_at,
  }
}

// Module-level singleton : la cloche, sa liste et les préférences voient le même état.
const unread = ref(0)
const items = ref<AppNotification[]>([])
const nextCursor = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const preferences = ref<NotificationPreference[]>([])
const preferencesError = ref<string | null>(null)

let timer: ReturnType<typeof setInterval> | undefined
let watching = false
let lastCountAt = 0

async function refreshCount() {
  lastCountAt = Date.now()
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications/unread-count`, { credentials: 'include' })
    if (!response.ok) return
    unread.value = (await response.json()).count
  } catch {
    // Hors ligne ou serveur indisponible : le compteur garde sa valeur, le relevé suivant réessaiera.
  }
}

// Un onglet resté en arrière-plan ralentit ses minuteurs : au retour, on relève si le dernier relevé date de plus d'une heure.
function onVisible() {
  if (document.visibilityState === 'visible' && Date.now() - lastCountAt >= COUNT_EVERY_MS) void refreshCount()
}

// Le compteur est relevé à l'ouverture, puis toutes les heures ; ouvrir le panneau recharge la liste et le compteur.
function startWatching() {
  if (watching) return
  watching = true
  void refreshCount()
  timer = setInterval(refreshCount, COUNT_EVERY_MS)
  document.addEventListener('visibilitychange', onVisible)
}

function stopWatching() {
  watching = false
  if (timer) clearInterval(timer)
  document.removeEventListener('visibilitychange', onVisible)
}

async function loadFirstPage() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications?limit=${PAGE_SIZE}`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const page: PageOut = await response.json()
    items.value = page.items.map(toNotification)
    nextCursor.value = page.next_cursor
    unread.value = page.unread
  } catch {
    error.value = 'Impossible de récupérer les notifications.'
  } finally {
    isLoading.value = false
  }
}

async function loadMore() {
  if (!nextCursor.value || isLoading.value) return
  isLoading.value = true
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/notifications?limit=${PAGE_SIZE}&cursor=${encodeURIComponent(nextCursor.value)}`,
      { credentials: 'include' },
    )
    if (!response.ok) throw new Error(`${response.status}`)
    const page: PageOut = await response.json()
    items.value = [...items.value, ...page.items.map(toNotification)]
    nextCursor.value = page.next_cursor
  } catch {
    error.value = 'Impossible de récupérer les notifications suivantes.'
  } finally {
    isLoading.value = false
  }
}

// Sans identifiant : toutes.
async function markRead(ids?: string[]) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications/read`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ids ? { ids } : {}),
    })
    if (!response.ok) return
    unread.value = (await response.json()).count
    items.value = items.value.map((item) => (!ids || ids.includes(item.id) ? { ...item, read: true } : item))
  } catch {
    // Le prochain relevé du compteur dira la vérité.
  }
}

async function remove(id: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications/${id}`, { method: 'DELETE', credentials: 'include' })
    if (!response.ok) return
    const removed = items.value.find((item) => item.id === id)
    items.value = items.value.filter((item) => item.id !== id)
    if (removed && !removed.read) unread.value = Math.max(0, unread.value - 1)
  } catch {
    // Elle reste dans la liste : la personne peut réessayer.
  }
}

async function loadPreferences() {
  preferencesError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications/preferences`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    preferences.value = await response.json()
  } catch {
    preferencesError.value = 'Impossible de récupérer vos préférences.'
  }
}

async function setPreference(type: string, app: boolean) {
  preferencesError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/notifications/preferences`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preferences: [{ type, app }] }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    preferences.value = await response.json()
  } catch {
    preferencesError.value = 'Impossible d’enregistrer ce choix.'
  }
}

export function useNotifications() {
  return {
    unread,
    items,
    hasMore: computed(() => nextCursor.value !== null),
    isLoading,
    error,
    preferences,
    preferencesError,
    startWatching,
    stopWatching,
    refreshCount,
    loadFirstPage,
    loadMore,
    markRead,
    remove,
    loadPreferences,
    setPreference,
  }
}
