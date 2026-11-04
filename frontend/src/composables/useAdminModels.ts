import { ref } from 'vue'
import type { ModelProfile } from '../types/model'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const models = ref<ModelProfile[]>([])
const classifierModel = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchModels() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/models`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { models: ModelProfile[]; classifier_model: string | null } = await response.json()
    models.value = body.models
    classifierModel.value = body.classifier_model
  } catch {
    error.value = 'Impossible de récupérer les modèles.'
  } finally {
    isLoading.value = false
  }
}

// Le score, la description et l'interrupteur « Auto » d'un modèle. Ses capacités ne sont jamais envoyées : le backend les
// calcule.
async function saveModel(
  id: string,
  profile: { score: number; description: string | null; auto_enabled: boolean },
): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/models/${encodeURIComponent(id)}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const saved: ModelProfile = await response.json()
    models.value = models.value.map((model) => (model.id === id ? saved : model))
    return true
  } catch {
    error.value = "Impossible d'enregistrer le modèle."
    return false
  }
}

async function saveClassifierModel(id: string | null): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/models/classifier`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classifier_model: id }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    classifierModel.value = id
    return true
  } catch {
    error.value = "Impossible d'enregistrer le modèle de classification."
    return false
  }
}

export function useAdminModels() {
  return { models, classifierModel, isLoading, error, fetchModels, saveModel, saveClassifierModel }
}
