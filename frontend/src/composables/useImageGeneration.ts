import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface ImageStatus {
  // Vrai seulement quand la fonction est activée, prête, et permise à cette personne : sinon le mode « Image » n'est
  // pas proposé du tout.
  available: boolean
  size: string | null
  dailyLimit: number | null
  remainingToday: number | null
  maxPromptChars: number | null
}

const NONE: ImageStatus = { available: false, size: null, dailyLimit: null, remainingToday: null, maxPromptChars: null }

// Module-level singleton : le composeur et la conversation voient le même état.
const imageStatus = ref<ImageStatus>({ ...NONE })

// Ce que le chat doit savoir pour proposer (ou non) le mode « Image ». Une erreur réseau ou un refus : pas de mode, sans
// message - la fonction est facultative, son absence n'est pas une panne.
async function loadImageStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/images/status`, { credentials: 'include' })
    if (!response.ok) {
      imageStatus.value = { ...NONE }
      return
    }
    const body: {
      available: boolean
      size: string | null
      daily_limit: number | null
      remaining_today: number | null
      max_prompt_chars: number | null
    } = await response.json()
    imageStatus.value = {
      available: body.available,
      size: body.size,
      dailyLimit: body.daily_limit,
      remainingToday: body.remaining_today,
      maxPromptChars: body.max_prompt_chars,
    }
  } catch {
    imageStatus.value = { ...NONE }
  }
}

export function useImageGeneration() {
  return { imageStatus, loadImageStatus }
}
