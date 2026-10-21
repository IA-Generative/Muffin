import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// A starter question for an empty chat (#126), drawn from the question/answer pairs of the
// collections the user can read. Clicking it shows the pair's own answer and source: no agent run.
export interface QaSuggestion {
  id: string
  question: string
  collectionId: string
  collectionName: string
}

interface QaSuggestionOut {
  id: string
  question: string
  collection_id: string
  collection_name: string
}

const suggestions = ref<QaSuggestion[]>([])
// Only the latest request may fill the list: the user can pin a collection while an earlier draw
// is still in flight, and a late answer would put back questions from the wrong scope.
let latestRequest = 0

async function loadSuggestions(collectionIds: string[] = []) {
  const request = ++latestRequest
  const query = new URLSearchParams()
  for (const id of collectionIds) query.append('collection_ids', id)
  try {
    const response = await fetch(`${API_BASE_URL}/api/qa-suggestions?${query}`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const raw: QaSuggestionOut[] = await response.json()
    if (request !== latestRequest) return
    suggestions.value = raw.map((item) => ({
      id: item.id,
      question: item.question,
      collectionId: item.collection_id,
      collectionName: item.collection_name,
    }))
  } catch {
    // Suggestions are a nicety: without them the welcome screen is just the plain one.
    if (request === latestRequest) suggestions.value = []
  }
}

export function useQaSuggestions() {
  return { suggestions, loadSuggestions }
}
