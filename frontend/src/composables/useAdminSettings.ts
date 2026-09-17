import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const embeddingModel = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchAdminSettings() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/settings`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { embedding_model: string | null } = await response.json()
    embeddingModel.value = body.embedding_model
  } catch {
    error.value = 'Impossible de récupérer les paramètres globaux.'
  } finally {
    isLoading.value = false
  }
}

async function updateEmbeddingModel(model: string) {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/settings/embedding-model`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ embedding_model: model }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { embedding_model: string | null } = await response.json()
    embeddingModel.value = body.embedding_model
  } catch {
    error.value = "Impossible d'enregistrer le modèle d'embedding."
  }
}

export function useAdminSettings() {
  return { embeddingModel, isLoading, error, fetchAdminSettings, updateEmbeddingModel }
}
