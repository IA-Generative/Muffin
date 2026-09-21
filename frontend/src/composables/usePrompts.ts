import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface PromptVersion {
  id: string
  name: string
  version: number
  content: string
  is_active: boolean
  created_at: string
}

interface PromptSummary {
  name: string
  active_version: PromptVersion | null
}

const summaries = ref<PromptSummary[]>([])
const versionsByName = ref<Record<string, PromptVersion[]>>({})
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchPrompts() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/prompts`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    summaries.value = await response.json()
  } catch {
    error.value = 'Impossible de récupérer les prompts.'
  } finally {
    isLoading.value = false
  }
}

async function fetchVersions(name: string) {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/prompts/${name}/versions`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    versionsByName.value = { ...versionsByName.value, [name]: await response.json() }
  } catch {
    error.value = `Impossible de récupérer l'historique de ${name}.`
  }
}

async function createVersion(name: string, content: string): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/prompts/${name}/versions`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    return true
  } catch {
    error.value = `Impossible de créer une nouvelle version de ${name}.`
    return false
  }
}

async function activateVersion(name: string, version: number): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/prompts/${name}/versions/${version}/activate`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    return true
  } catch {
    error.value = `Impossible d'activer cette version de ${name}.`
    return false
  }
}

export function usePrompts() {
  return { summaries, versionsByName, isLoading, error, fetchPrompts, fetchVersions, createVersion, activateVersion }
}
