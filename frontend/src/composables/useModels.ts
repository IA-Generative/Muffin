import { computed, ref } from 'vue'
import type { ChatModel } from '../types/model'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const SELECTED_MODEL_STORAGE_KEY = 'muffin.selectedModelId'

const models = ref<ChatModel[]>([])
const selectedModelId = ref<string | null>(localStorage.getItem(SELECTED_MODEL_STORAGE_KEY))
const isLoading = ref(true)
const error = ref<string | null>(null)

const selectedModel = computed(() => models.value.find((model) => model.id === selectedModelId.value) ?? null)

async function fetchModels() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/models`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { models: ChatModel[] } = await response.json()
    models.value = body.models

    if (!selectedModelId.value || !models.value.some((model) => model.id === selectedModelId.value)) {
      selectModel(models.value[0]?.id ?? null)
    }
  } catch {
    error.value = "Impossible de récupérer la liste des modèles."
  } finally {
    isLoading.value = false
  }
}

function selectModel(id: string | null) {
  selectedModelId.value = id
  if (id) localStorage.setItem(SELECTED_MODEL_STORAGE_KEY, id)
  else localStorage.removeItem(SELECTED_MODEL_STORAGE_KEY)
}

fetchModels()

export function useModels() {
  return { models, selectedModelId, selectedModel, isLoading, error, selectModel, refresh: fetchModels }
}
