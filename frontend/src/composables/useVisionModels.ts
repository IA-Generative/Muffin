import { ref } from 'vue'
import type { ChatModel } from '../types/model'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Les modèles de chat du hub qui lisent les images : ceux qu'on peut choisir pour décrire les images d'un scan.
const models = ref<ChatModel[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)

async function fetchVisionModels() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/vision-models`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { models: ChatModel[] } = await response.json()
    models.value = body.models
  } catch {
    error.value = 'Impossible de récupérer la liste des modèles qui lisent les images.'
  } finally {
    isLoading.value = false
  }
}

fetchVisionModels()

export function useVisionModels() {
  return { models, isLoading, error, refresh: fetchVisionModels }
}
