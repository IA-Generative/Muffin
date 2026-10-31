import { ref } from 'vue'
import type { ApiKey } from '../utils/apiKeys'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface CreatedApiKey extends ApiKey {
  // The key itself: in the answer to its creation and nowhere else.
  key: string
}

async function problem(response: Response): Promise<string> {
  if (response.status === 503) return "Les clés d'API ne sont pas activées sur ce serveur."
  if (response.status === 409) return 'Trop de clés : révoquez-en une avant d\'en créer une autre.'
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // No body to read.
  }
  return `La requête a échoué (${response.status}).`
}

// The page of the personal API keys (#521). The key just made is kept here, in memory, until it is dismissed: nothing
// else - not the list, not the storage of the browser - ever holds it.
export function useApiKeys() {
  const keys = ref<ApiKey[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const created = ref<CreatedApiKey | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(`${API_BASE_URL}/api/api-keys`, { credentials: 'include' })
      if (!response.ok) throw new Error(await problem(response))
      keys.value = await response.json()
    } catch (failure) {
      error.value = (failure as Error).message
    } finally {
      loading.value = false
    }
  }

  async function create(name: string, scopes: string[], expiresInDays: number): Promise<boolean> {
    error.value = null
    try {
      const response = await fetch(`${API_BASE_URL}/api/api-keys`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, scopes, expires_in_days: expiresInDays }),
      })
      if (!response.ok) throw new Error(await problem(response))
      created.value = await response.json()
      await load()
      return true
    } catch (failure) {
      error.value = (failure as Error).message
      return false
    }
  }

  async function revoke(id: string) {
    error.value = null
    try {
      const response = await fetch(`${API_BASE_URL}/api/api-keys/${id}`, { method: 'DELETE', credentials: 'include' })
      if (!response.ok) throw new Error(await problem(response))
      await load()
    } catch (failure) {
      error.value = (failure as Error).message
    }
  }

  function dismissCreated() {
    created.value = null
  }

  return { keys, loading, error, created, load, create, revoke, dismissCreated }
}
