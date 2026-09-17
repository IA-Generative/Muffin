import { ref } from 'vue'
import type { ChatModel } from '../types/model'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const models = ref<ChatModel[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)

async function fetchEmbeddingModels() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/embedding-models`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { models: ChatModel[] } = await response.json()
    models.value = body.models
  } catch {
    error.value = "Impossible de récupérer la liste des modèles d'embedding."
  } finally {
    isLoading.value = false
  }
}

fetchEmbeddingModels()

export function useEmbeddingModels() {
  return { models, isLoading, error, refresh: fetchEmbeddingModels }
}
