import { computed, ref } from 'vue'
import type { Assistant, AssistantDraft, AssistantShare, AssistantVisibility } from '../types/assistant'
import type { SharePermission, ShareSubjectType } from '../types/collection'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const STORAGE_KEY = 'muffin.assistant'

interface AssistantOut {
  id: string
  name: string
  description: string
  icon: string
  color: string
  instructions: string | null
  instructions_hidden: boolean
  hide_instructions: boolean
  collections: { id: string; name: string }[]
  inaccessible_collection_count: number
  include_descendants: boolean
  web_search_allowed: boolean
  disabled_tools: string[]
  suggestions: string[]
  visibility: AssistantVisibility
  version: number
  is_owner: boolean
  can_edit: boolean
  share_count: number
  updated_at: string
}

interface ShareOut {
  id: string
  subject_type: ShareSubjectType
  status: AssistantShare['status']
  permission: SharePermission
  display_hint: string
  created_at: string
}

function toAssistant(raw: AssistantOut): Assistant {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    icon: raw.icon,
    color: raw.color,
    instructions: raw.instructions,
    instructionsHidden: raw.instructions_hidden,
    hideInstructions: raw.hide_instructions,
    collections: raw.collections,
    inaccessibleCollectionCount: raw.inaccessible_collection_count,
    includeDescendants: raw.include_descendants,
    webSearchAllowed: raw.web_search_allowed,
    disabledTools: raw.disabled_tools,
    suggestions: raw.suggestions,
    visibility: raw.visibility,
    version: raw.version,
    isOwner: raw.is_owner,
    canEdit: raw.can_edit,
    shareCount: raw.share_count,
    updatedAt: raw.updated_at,
  }
}

function toShare(raw: ShareOut): AssistantShare {
  return {
    id: raw.id,
    subjectType: raw.subject_type,
    status: raw.status,
    permission: raw.permission,
    displayHint: raw.display_hint,
    createdAt: raw.created_at,
    inheritedFrom: null,
  }
}

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function remember(id: string | null) {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Private window or blocked storage: the choice only lasts until the page is closed.
  }
}

// Module-level singleton, like useCollections : le sélecteur du chat, la page des assistants et l'envoi des messages voient
// la même liste et le même choix.
const assistants = ref<Assistant[]>([])
const isLoading = ref(false)
const assistantError = ref<string | null>(null)
const selectedAssistantId = ref<string | null>(remembered())

const selectedAssistant = computed(() => assistants.value.find((item) => item.id === selectedAssistantId.value) ?? null)

function select(id: string | null) {
  selectedAssistantId.value = id
  remember(id)
}

async function request(path: string, init?: RequestInit): Promise<Response | null> {
  try {
    return await fetch(`${API_BASE_URL}/api/assistants${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    assistantError.value = 'Le serveur est inaccessible.'
    return null
  }
}

// Ce que dit le serveur quand on ne peut pas faire une chose : dit clairement, pas « échec ».
function describe(response: Response, fallback: string): string {
  if (response.status === 403) return 'Seul l’auteur de cet assistant peut faire cela (ou un droit d’écriture pour le modifier).'
  if (response.status === 404) return 'Cet assistant n’existe plus ou ne vous est plus partagé.'
  if (response.status === 409) return 'Vous avez atteint le nombre maximal d’assistants.'
  if (response.status === 422) return 'Un champ n’est pas valide : vérifiez le nom, les consignes (4 000 caractères) et les questions suggérées.'
  return fallback
}

async function refreshAssistants() {
  isLoading.value = true
  try {
    const response = await request('')
    if (response?.ok) {
      assistants.value = ((await response.json()) as AssistantOut[]).map(toAssistant)
      // Un assistant retiré ou qui n'est plus partagé : le chat retombe sur « sans assistant ».
      if (selectedAssistantId.value && !assistants.value.some((item) => item.id === selectedAssistantId.value)) select(null)
    }
  } finally {
    isLoading.value = false
  }
}

function toBody(draft: AssistantDraft): Record<string, unknown> {
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    icon: draft.icon.trim(),
    instructions: draft.instructions,
    hide_instructions: draft.hideInstructions,
    collection_ids: draft.collectionIds,
    include_descendants: draft.includeDescendants,
    web_search_allowed: draft.webSearchAllowed,
    disabled_tools: draft.disabledTools,
    suggestions: draft.suggestions
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
  }
}

function upsert(assistant: Assistant) {
  const known = assistants.value.some((item) => item.id === assistant.id)
  assistants.value = known
    ? assistants.value.map((item) => (item.id === assistant.id ? assistant : item))
    : [...assistants.value, assistant].sort((a, b) => a.name.localeCompare(b.name, 'fr'))
}

async function saveAssistant(draft: AssistantDraft, id?: string): Promise<Assistant | null> {
  assistantError.value = null
  const response = await request(id ? `/${id}` : '', { method: id ? 'PATCH' : 'POST', body: JSON.stringify(toBody(draft)) })
  if (!response) return null
  if (!response.ok) {
    assistantError.value = describe(response, 'Échec de l’enregistrement de l’assistant.')
    return null
  }
  const assistant = toAssistant(await response.json())
  upsert(assistant)
  return assistant
}

async function duplicateAssistant(id: string): Promise<Assistant | null> {
  assistantError.value = null
  const response = await request(`/${id}/duplicate`, { method: 'POST' })
  if (!response) return null
  if (!response.ok) {
    assistantError.value = describe(response, 'Échec de la duplication.')
    return null
  }
  const assistant = toAssistant(await response.json())
  upsert(assistant)
  return assistant
}

async function deleteAssistant(id: string): Promise<boolean> {
  assistantError.value = null
  const response = await request(`/${id}`, { method: 'DELETE' })
  if (!response) return false
  if (!response.ok) {
    assistantError.value = describe(response, 'Échec de la suppression.')
    return false
  }
  assistants.value = assistants.value.filter((item) => item.id !== id)
  if (selectedAssistantId.value === id) select(null)
  return true
}

async function setVisibility(id: string, visibility: AssistantVisibility): Promise<boolean> {
  assistantError.value = null
  const response = await request(`/${id}/visibility`, { method: 'PUT', body: JSON.stringify({ visibility }) })
  if (!response) return false
  if (response.status === 403 && visibility === 'public') {
    assistantError.value = 'Publier un assistant à toute l’organisation n’est pas autorisé sur ce serveur.'
    return false
  }
  if (!response.ok) {
    assistantError.value = describe(response, 'Échec du changement de visibilité.')
    return false
  }
  upsert(toAssistant(await response.json()))
  return true
}

async function fetchShares(id: string): Promise<AssistantShare[]> {
  const response = await request(`/${id}/shares`)
  if (!response?.ok) return []
  return ((await response.json()) as ShareOut[]).map(toShare)
}

interface ShareTarget {
  subjectType: ShareSubjectType
  identifier?: string
  groupId?: string
  permission: SharePermission
}

async function createShare(id: string, target: ShareTarget): Promise<boolean> {
  assistantError.value = null
  const body: Record<string, string> = { subject_type: target.subjectType, permission: target.permission }
  if (target.groupId) body.group_id = target.groupId
  else if (target.identifier?.trim()) body.identifier = target.identifier.trim()
  else return false
  const response = await request(`/${id}/shares`, { method: 'POST', body: JSON.stringify(body) })
  if (!response) return false
  if (response.status === 409) assistantError.value = 'Cette personne ou ce groupe est déjà invité.'
  else if (response.status === 404 && target.groupId) assistantError.value = 'Ce groupe n’existe plus ou vous n’en faites pas partie.'
  else if (response.status === 503) assistantError.value = 'Le partage n’est pas configuré sur ce serveur.'
  else if (!response.ok) assistantError.value = describe(response, 'Échec de l’invitation.')
  if (!response.ok) return false
  await refreshAssistants()
  return true
}

async function updateSharePermission(id: string, shareId: string, permission: SharePermission): Promise<boolean> {
  assistantError.value = null
  const response = await request(`/${id}/shares/${shareId}`, { method: 'PATCH', body: JSON.stringify({ permission }) })
  if (!response?.ok) {
    if (response) assistantError.value = describe(response, 'Échec du changement de droit.')
    return false
  }
  return true
}

async function deleteShare(id: string, shareId: string): Promise<boolean> {
  assistantError.value = null
  const response = await request(`/${id}/shares/${shareId}`, { method: 'DELETE' })
  if (!response?.ok) {
    if (response) assistantError.value = describe(response, 'Échec du retrait du partage.')
    return false
  }
  await refreshAssistants()
  return true
}

export function useAssistants() {
  return {
    assistants,
    isLoading,
    assistantError,
    selectedAssistantId,
    selectedAssistant,
    select,
    refreshAssistants,
    saveAssistant,
    duplicateAssistant,
    deleteAssistant,
    setVisibility,
    fetchShares,
    createShare,
    updateSharePermission,
    deleteShare,
  }
}
