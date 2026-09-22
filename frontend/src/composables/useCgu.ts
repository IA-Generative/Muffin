import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface CguStatus {
  version: number | null
  content: string | null
  accepted: boolean
  isUpdate: boolean
}

interface CguStatusOut {
  version: number | null
  content: string | null
  accepted: boolean
  is_update: boolean
}

function toStatus(raw: CguStatusOut): CguStatus {
  return { version: raw.version, content: raw.content, accepted: raw.accepted, isUpdate: raw.is_update }
}

// Module-level singleton, same reasoning as useCurrentUser's `user` - the whole app shares one
// gating state, checked once at boot (see App.vue) rather than once per component that cares.
const status = ref<CguStatus | null>(null)
const isLoading = ref(true)
const error = ref<string | null>(null)

async function fetchCguStatus() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/cgu/status`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    status.value = toStatus(await response.json())
  } catch {
    error.value = 'Impossible de récupérer les CGU.'
  } finally {
    isLoading.value = false
  }
}

async function acceptCgu(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/cgu/accept`, { method: 'POST', credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    status.value = toStatus(await response.json())
    return true
  } catch {
    error.value = "Impossible d'enregistrer votre acceptation des CGU - veuillez réessayer."
    return false
  }
}

export function useCgu() {
  return { status, isLoading, error, fetchCguStatus, acceptCgu }
}
