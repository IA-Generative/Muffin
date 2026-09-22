import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface CguVersion {
  id: string
  version: number
  content: string
  is_active: boolean
  created_at: string
}

const versions = ref<CguVersion[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchVersions() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/cgu/versions`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    versions.value = await response.json()
  } catch {
    error.value = "Impossible de récupérer les versions des CGU."
  } finally {
    isLoading.value = false
  }
}

async function createVersion(content: string): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/cgu/versions`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    await fetchVersions()
    return true
  } catch {
    error.value = "Impossible de créer une nouvelle version des CGU."
    return false
  }
}

async function activateVersion(version: number): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/cgu/versions/${version}/activate`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    await fetchVersions()
    return true
  } catch {
    error.value = "Impossible d'activer cette version des CGU."
    return false
  }
}

export function useCguAdmin() {
  return { versions, isLoading, error, fetchVersions, createVersion, activateVersion }
}
