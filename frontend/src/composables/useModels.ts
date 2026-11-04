import { computed, ref } from 'vue'
import { AUTO_MODEL_ID, type ChatModel } from '../types/model'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const SELECTED_MODEL_STORAGE_KEY = 'muffin.selectedModelId'

const models = ref<ChatModel[]>([])
// « Auto » par défaut : l'agent choisit le modèle selon la difficulté de la demande.
const selectedModelId = ref<string>(localStorage.getItem(SELECTED_MODEL_STORAGE_KEY) ?? AUTO_MODEL_ID)
const isLoading = ref(true)
const error = ref<string | null>(null)

const isAuto = computed(() => selectedModelId.value === AUTO_MODEL_ID)
const selectedModel = computed(() => models.value.find((model) => model.id === selectedModelId.value) ?? null)

async function fetchModels() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/models`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { models: ChatModel[] } = await response.json()
    models.value = body.models

    // Un modèle choisi à la main qui n'existe plus : retour à Auto.
    if (!isAuto.value && !models.value.some((model) => model.id === selectedModelId.value)) {
      selectModel(AUTO_MODEL_ID)
    }
  } catch {
    error.value = "Impossible de récupérer la liste des modèles."
  } finally {
    isLoading.value = false
  }
}

function selectModel(id: string) {
  selectedModelId.value = id
  localStorage.setItem(SELECTED_MODEL_STORAGE_KEY, id)
}

fetchModels()

export function useModels() {
  return { models, selectedModelId, selectedModel, isAuto, isLoading, error, selectModel, refresh: fetchModels }
}
