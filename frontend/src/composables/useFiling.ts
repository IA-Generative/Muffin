import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// One scored candidate collection behind a suggestion - "collectionDescription" is shown as the
// "why" (§122 follow-up: "l'explication de pourquoi") - the matched collection's own
// description, not a generated rationale.
export interface FilingSuggestionCandidate {
  collectionId: string
  collectionName: string
  collectionDescription: string
  score: number
}

export interface FilingCandidate {
  id: string
  name: string
  addedByDisplay: string | null
  collectionId: string
  collectionName: string
  collectionIsTemporary: boolean
  collectionEditable: boolean
  suggestedCollectionId: string | null
  suggestedCollectionName: string | null
  suggestedCollectionScore: number | null
  filingCandidates: FilingSuggestionCandidate[]
  filingDismissed: boolean
  createdAt: string
}

interface FilingSuggestionCandidateOut {
  collection_id: string
  collection_name: string
  collection_description: string
  score: number
}

// Backend response shape (snake_case) - see backend/app/schemas/document.py's FilingCandidateOut.
interface FilingCandidateOut {
  id: string
  name: string
  added_by_display: string | null
  collection_id: string
  collection_name: string
  collection_is_temporary: boolean
  collection_editable: boolean
  suggested_collection_id: string | null
  suggested_collection_name: string | null
  suggested_collection_score: number | null
  filing_candidates: FilingSuggestionCandidateOut[] | null
  filing_dismissed: boolean
  created_at: string
}

function toCandidate(raw: FilingCandidateOut): FilingCandidate {
  return {
    id: raw.id,
    name: raw.name,
    addedByDisplay: raw.added_by_display,
    collectionId: raw.collection_id,
    collectionName: raw.collection_name,
    collectionIsTemporary: raw.collection_is_temporary,
    collectionEditable: raw.collection_editable,
    suggestedCollectionId: raw.suggested_collection_id,
    suggestedCollectionName: raw.suggested_collection_name,
    suggestedCollectionScore: raw.suggested_collection_score,
    filingCandidates: (raw.filing_candidates ?? []).map((item) => ({
      collectionId: item.collection_id,
      collectionName: item.collection_name,
      collectionDescription: item.collection_description,
      score: item.score,
    })),
    filingDismissed: raw.filing_dismissed,
    createdAt: raw.created_at,
  }
}

const candidates = ref<FilingCandidate[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchFilingCandidates() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/filing/documents`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    candidates.value = (await response.json()).map(toCandidate)
  } catch {
    error.value = 'Impossible de récupérer les fichiers à ranger.'
  } finally {
    isLoading.value = false
  }
}

// Shared by the chat's file-filing modal and this review page - both remove/update the same
// candidate by id so neither goes stale relative to the other. Throws on failure so callers
// (which show their own inline error state) can react - unlike fetchFilingCandidates, there's
// no single natural place here to put a generic error message.
async function decideFiling(
  documentId: string,
  action: 'accept' | 'choose_other' | 'dismiss',
  targetCollectionId?: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/filing/documents/${documentId}/decision`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, target_collection_id: targetCollectionId }),
  })
  if (!response.ok) throw new Error(`${response.status}`)
  if (action === 'dismiss') {
    const candidate = candidates.value.find((item) => item.id === documentId)
    if (candidate) candidate.filingDismissed = true
  } else {
    // Filed into a permanent collection - no longer "to file", drop it from both surfaces.
    candidates.value = candidates.value.filter((item) => item.id !== documentId)
  }
}

// Upload a file straight to the review page, no conversation involved (§122 follow-up) -
// refreshes the whole list afterwards rather than appending locally, since the backend still
// needs to process/summarize/suggest before this file is actually worth showing with anything
// useful in it.
async function uploadStandaloneFile(file: File): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE_URL}/api/filing/documents/upload`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  })
  if (!response.ok) throw new Error(`${response.status}`)
  await fetchFilingCandidates()
}

export function useFiling() {
  return { candidates, isLoading, error, fetchFilingCandidates, decideFiling, uploadStandaloneFile }
}
