import { ref } from 'vue'
import type { FilingSuggestionCandidate } from '../types/chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// A ZIP turned into a collection and its sub-collections (#223). 'queued' / 'uploading' /
// 'upload_failed' are local-only states, before the backend knows about the import; the rest
// mirror the backend's CollectionImportStatus.
export type CollectionImportStatus = 'queued' | 'uploading' | 'upload_failed' | 'pending' | 'running' | 'completed' | 'failed'

// See CollectionImportOut.attach_status in the backend: whether this import still awaits an
// answer about where to attach its collection.
export type AttachStatus = 'not_applicable' | 'pending' | 'attached' | 'dismissed'

export interface CollectionImportSummary {
  collectionsCreated: number
  documentsCreated: number
  skipped: { path: string; reason: string }[]
}

export interface CollectionImport {
  id: string
  status: CollectionImportStatus
  archiveName: string
  rootCollectionId: string | null
  rootCollectionName: string | null
  conversationId: string | null
  summary: CollectionImportSummary | null
  // A message for the user: the backend's own, or an upload refusal mapped below.
  error: string | null
  attachStatus: AttachStatus
  attachCandidates: FilingSuggestionCandidate[]
}

interface CollectionImportOut {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  archive_name: string
  root_collection_id: string | null
  root_collection_name: string | null
  conversation_id: string | null
  summary: { collections_created: number; documents_created: number; skipped: { path: string; reason: string }[] } | null
  error: string | null
  attach_status: AttachStatus
  attach_candidates: { collection_id: string; collection_name: string; collection_description: string; score: number }[]
}

function toImport(raw: CollectionImportOut): CollectionImport {
  return {
    id: raw.id,
    status: raw.status,
    archiveName: raw.archive_name,
    rootCollectionId: raw.root_collection_id,
    rootCollectionName: raw.root_collection_name,
    conversationId: raw.conversation_id,
    summary: raw.summary
      ? {
          collectionsCreated: raw.summary.collections_created,
          documentsCreated: raw.summary.documents_created,
          skipped: raw.summary.skipped,
        }
      : null,
    error: raw.error,
    attachStatus: raw.attach_status,
    attachCandidates: raw.attach_candidates.map((candidate) => ({
      collectionId: candidate.collection_id,
      collectionName: candidate.collection_name,
      collectionDescription: candidate.collection_description,
      score: candidate.score,
    })),
  }
}

function localImport(id: string, file: File, status: CollectionImportStatus, error: string | null = null): CollectionImport {
  return {
    id,
    status,
    archiveName: file.name,
    rootCollectionId: null,
    rootCollectionName: null,
    conversationId: null,
    summary: null,
    error,
    attachStatus: 'not_applicable',
    attachCandidates: [],
  }
}

export function isZip(file: File): boolean {
  return file.name.toLowerCase().endsWith('.zip')
}

export function isImportFinished(item: CollectionImport): boolean {
  return item.status === 'completed' || item.status === 'failed' || item.status === 'upload_failed'
}

// Every import this session knows about, by id - shared by the chat, the collection page and the
// "Fichiers à ranger" page, so a decision taken in one shows everywhere.
const imports = ref<Record<string, CollectionImport>>({})
const importIdsByConversation = ref<Record<string, string[]>>({})
// Dropped before the conversation has a backend id - uploaded once it gets one, like a plain
// conversation file (see useChat's migrateConversationId).
const queuedByConversation = new Map<string, { tempId: string; file: File }[]>()
const polls = new Map<string, ReturnType<typeof setInterval>>()

// The suggestion only comes once the pipeline has described the new collection (a minute or more
// after the import itself) - polled that long at most.
const POLL_INTERVAL_MS = 3000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

function store(item: CollectionImport, replacing?: string) {
  if (replacing && replacing !== item.id) {
    delete imports.value[replacing]
    for (const ids of Object.values(importIdsByConversation.value)) {
      const index = ids.indexOf(replacing)
      if (index !== -1) ids[index] = item.id
    }
  }
  imports.value[item.id] = item
}

function trackInConversation(conversationId: string, id: string) {
  const ids = importIdsByConversation.value[conversationId] ?? []
  if (!ids.includes(id)) importIdsByConversation.value[conversationId] = [...ids, id]
}

function stillWorthPolling(item: CollectionImport): boolean {
  return !isImportFinished(item) || (item.attachStatus === 'pending' && item.attachCandidates.length === 0)
}

function poll(id: string) {
  if (polls.has(id)) return
  const startedAt = Date.now()
  polls.set(
    id,
    setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/collection-imports/${id}`, { credentials: 'include' })
        if (response.ok) store(toImport(await response.json()))
      } catch {
        // Best-effort: the next tick tries again.
      }
      const item = imports.value[id]
      if (!item || !stillWorthPolling(item) || Date.now() - startedAt > POLL_TIMEOUT_MS) {
        clearInterval(polls.get(id))
        polls.delete(id)
      }
    }, POLL_INTERVAL_MS),
  )
}

function uploadErrorMessage(status: number): string {
  // Muffin itself sets no size limit on an archive: a 413 comes from a proxy in front of it.
  if (status === 413) return "L'archive a été refusée par le serveur : elle dépasse la taille qu'il accepte."
  if (status === 422) return "Ce fichier n'est pas une archive ZIP valide."
  return "Impossible d'envoyer l'archive."
}

// Uploads `file` and follows the import. `parentId`: dropped into a collection, its collection goes
// right under it. `conversationId`: dropped into a conversation. Neither: the "Fichiers à ranger"
// page. Returns the import, local id included when the upload itself failed.
async function startImport(
  file: File,
  options: { parentId?: string; conversationId?: string; tempId?: string } = {},
): Promise<CollectionImport> {
  const tempId = options.tempId ?? crypto.randomUUID()
  store(localImport(tempId, file, 'uploading'))
  const formData = new FormData()
  formData.append('file', file)
  if (options.parentId) formData.append('parent_id', options.parentId)
  if (options.conversationId) formData.append('conversation_id', options.conversationId)
  try {
    const response = await fetch(`${API_BASE_URL}/api/collection-imports`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })
    if (!response.ok) {
      store(localImport(tempId, file, 'upload_failed', uploadErrorMessage(response.status)))
      return imports.value[tempId]
    }
    const created = toImport(await response.json())
    store(created, tempId)
    poll(created.id)
    return created
  } catch {
    store(localImport(tempId, file, 'upload_failed', "Impossible d'envoyer l'archive : le serveur est inaccessible."))
    return imports.value[tempId]
  }
}

// From the chat: uploaded right away if the conversation already exists backend-side, otherwise
// queued until flushConversation is told its real id.
function importIntoConversation(conversationId: string, file: File, conversationExists: boolean) {
  const tempId = crypto.randomUUID()
  store(localImport(tempId, file, conversationExists ? 'uploading' : 'queued'))
  trackInConversation(conversationId, tempId)
  if (conversationExists) {
    startImport(file, { conversationId, tempId })
  } else {
    const queued = queuedByConversation.get(conversationId) ?? []
    queued.push({ tempId, file })
    queuedByConversation.set(conversationId, queued)
  }
}

// Called by useChat once a brand-new conversation gets its backend id.
function flushConversation(placeholderId: string, realId: string) {
  if (placeholderId !== realId && importIdsByConversation.value[placeholderId]) {
    importIdsByConversation.value[realId] = [
      ...(importIdsByConversation.value[realId] ?? []),
      ...importIdsByConversation.value[placeholderId],
    ]
    delete importIdsByConversation.value[placeholderId]
  }
  const queued = queuedByConversation.get(placeholderId)
  if (!queued) return
  queuedByConversation.delete(placeholderId)
  for (const { tempId, file } of queued) startImport(file, { conversationId: realId, tempId })
}

// Restores a conversation's imports (page reload, conversation switch) and resumes following the
// ones still running or waiting for their suggestion.
async function loadConversationImports(conversationId: string) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collection-imports?conversation_id=${encodeURIComponent(conversationId)}`,
      { credentials: 'include' },
    )
    if (!response.ok) return
    const items = ((await response.json()) as CollectionImportOut[]).map(toImport).reverse()
    for (const item of items) {
      store(item)
      trackInConversation(conversationId, item.id)
      if (stillWorthPolling(item)) poll(item.id)
    }
  } catch {
    // Best-effort: the conversation just shows no import chip until the next visit.
  }
}

const awaitingAttachment = ref<CollectionImport[]>([])

async function fetchAwaitingAttachment() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collection-imports?awaiting_attachment=true`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const items = ((await response.json()) as CollectionImportOut[]).map(toImport)
    items.forEach((item) => store(item))
    awaitingAttachment.value = items
  } catch {
    // Best-effort, the page keeps what it last had.
  }
}

// Throws on failure so the caller can keep its notification for a retry, like useFiling.decideFiling.
async function decideAttachment(
  importId: string,
  action: 'accept' | 'choose_other' | 'dismiss',
  targetCollectionId?: string,
): Promise<CollectionImport> {
  const response = await fetch(`${API_BASE_URL}/api/collection-imports/${importId}/attach`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, target_collection_id: targetCollectionId }),
  })
  if (!response.ok) throw new Error(`${response.status}`)
  const updated = toImport(await response.json())
  store(updated)
  awaitingAttachment.value = awaitingAttachment.value.filter((item) => item.id !== importId)
  return updated
}

export function useCollectionImports() {
  return {
    imports,
    importIdsByConversation,
    awaitingAttachment,
    startImport,
    importIntoConversation,
    flushConversation,
    loadConversationImports,
    fetchAwaitingAttachment,
    decideAttachment,
  }
}
