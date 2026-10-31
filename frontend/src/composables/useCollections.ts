import { computed, ref } from 'vue'
import { router } from '../router'
import type {
  ChunkingSettings,
  ChunkStrategy,
  Chunk,
  Collection,
  CollectionDocument,
  CollectionPathItem,
  CollectionVisibility,
  Entity,
  EvaluationRun,
  IndexRebuild,
  FieldStamp,
  CaptionEngine,
  GenerationModels,
  IndexingEstimate,
  PipelineInstructions,
  PipelineWindows,
  QaPair,
  Relation,
  Share,
  SharePermission,
  ShareSubjectType,
} from '../types/collection'
import type { LongDocumentsPayload } from '../utils/longDocuments'
import type { SettingsPatch } from '../utils/settingsDraft'
import type { RefreshSchedule } from '../utils/refreshSchedule'

// Backend response is snake_case; the rest of the app uses camelCase.
interface CollectionOut {
  id: string
  name: string
  description: string
  description_meta: { updated_by: string; updated_at: string } | null
  tags: string[]
  tags_meta: { updated_by: string; updated_at: string } | null
  updated_at: string
  visibility: CollectionVisibility
  is_owner: boolean
  can_edit: boolean
  copied?: boolean
  adopted?: boolean
  parent_id: string | null
  path: CollectionPathItem[]
  children_count: number
  document_count: number
  indexed_document_count: number
  inherited_public_from: CollectionPathItem | null
  documents: CollectionDocument[]
  qa_pairs: QaPair[]
  entities: Entity[]
  relations: Relation[]
  chunks: Chunk[]
  evaluation_runs: EvaluationRun[]
  chunking_settings: { strategy: ChunkingSettings['strategy']; chunk_size: number; chunk_overlap: number }
  embedding_model: string
  index_embedding_model: string | null
  reindex_required: boolean
  instructions: PipelineInstructions
  generation_models: GenerationModels
  caption_engine?: CaptionEngine
  caption_model?: string | null
  pipeline_windows: {
    summary_pages_per_map: number
    qa_window_pages: number
    qa_slide_pages: number
    qa_questions_per_window: number
    extraction_window_pages: number
    extraction_slide_pages: number
    chunking_window_pages: number
    chunking_slide_pages: number
    collection_qa_count: number
    sampling_min_pages: number
    summary_mode: PipelineWindows['summaryMode']
    summary_percent: number
    summary_head_percent: number | null
    summary_tail_percent: number | null
    summary_page_ranges: string
    qa_max_questions: number | null
    extraction_percent: number
    extraction_max_windows: number | null
  }
}

function toPipelineWindows(raw: CollectionOut['pipeline_windows']): PipelineWindows {
  return {
    summaryPagesPerMap: raw.summary_pages_per_map,
    qaWindowPages: raw.qa_window_pages,
    qaSlidePages: raw.qa_slide_pages,
    qaQuestionsPerWindow: raw.qa_questions_per_window,
    extractionWindowPages: raw.extraction_window_pages,
    extractionSlidePages: raw.extraction_slide_pages,
    chunkingWindowPages: raw.chunking_window_pages,
    chunkingSlidePages: raw.chunking_slide_pages,
    collectionQaCount: raw.collection_qa_count,
    samplingMinPages: raw.sampling_min_pages,
    summaryMode: raw.summary_mode,
    summaryPercent: raw.summary_percent,
    summaryHeadPercent: raw.summary_head_percent,
    summaryTailPercent: raw.summary_tail_percent,
    summaryPageRanges: raw.summary_page_ranges,
    qaMaxQuestions: raw.qa_max_questions,
    extractionPercent: raw.extraction_percent,
    extractionMaxWindows: raw.extraction_max_windows,
  }
}

function toStamp(meta: CollectionOut['description_meta']): FieldStamp | null {
  return meta ? { updatedBy: meta.updated_by, updatedAt: meta.updated_at } : null
}

function toCollection(raw: CollectionOut): Collection {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    descriptionMeta: toStamp(raw.description_meta),
    tags: raw.tags,
    tagsMeta: toStamp(raw.tags_meta),
    updatedAt: raw.updated_at,
    visibility: raw.visibility,
    isOwner: raw.is_owner,
    canEdit: raw.can_edit,
    copied: raw.copied ?? false,
    adopted: raw.adopted ?? false,
    canManage: raw.is_owner && !raw.copied,
    parentId: raw.parent_id,
    path: raw.path,
    childrenCount: raw.children_count,
    documentCount: raw.document_count,
    indexedDocumentCount: raw.indexed_document_count,
    inheritedPublicFrom: raw.inherited_public_from,
    documents: raw.documents,
    qaPairs: raw.qa_pairs,
    entities: raw.entities,
    relations: raw.relations,
    chunks: raw.chunks,
    chunkingSettings: {
      strategy: raw.chunking_settings.strategy,
      chunkSize: raw.chunking_settings.chunk_size,
      chunkOverlap: raw.chunking_settings.chunk_overlap,
    },
    embeddingModel: raw.embedding_model,
    indexEmbeddingModel: raw.index_embedding_model ?? null,
    reindexRequired: raw.reindex_required,
    instructions: raw.instructions,
    generationModels: raw.generation_models,
    pipelineWindows: toPipelineWindows(raw.pipeline_windows),
    captionEngine: raw.caption_engine ?? 'local',
    captionModel: raw.caption_model ?? null,
    evaluationRuns: raw.evaluation_runs,
    // Not embedded in CollectionOut (owner-only, would 404/leak nothing useful for a viewer
    // anyway) - fetched separately by refreshShares, see CollectionSettingsTab.
    shares: [],
  }
}

// Backend response is snake_case; matches Share once mapped.
interface ShareOut {
  id: string
  subject_type: ShareSubjectType
  status: Share['status']
  permission: SharePermission
  display_hint: string
  created_at: string
  inherited_from: CollectionPathItem | null
}

function toShare(raw: ShareOut): Share {
  return {
    id: raw.id,
    subjectType: raw.subject_type,
    status: raw.status,
    permission: raw.permission,
    displayHint: raw.display_hint,
    createdAt: raw.created_at,
    inheritedFrom: raw.inherited_from,
  }
}

interface DocumentOut {
  id: string
  name: string
  type: CollectionDocument['type']
  // Absent from a backend older than #174 - treated as a standard document.
  kind?: CollectionDocument['kind']
  status: CollectionDocument['status']
  progress: number
}

function toDocument(raw: DocumentOut): CollectionDocument {
  return { id: raw.id, name: raw.name, type: raw.type, kind: raw.kind ?? 'standard', status: raw.status, progress: raw.progress }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Backend's default name for a freshly created collection - used to detect
// "not renamed yet" without a dedicated flag.
const DEFAULT_COLLECTION_NAME = 'Nouvelle collection'
const SETTINGS_SAVED_STORAGE_KEY = 'muffin.collectionsWithSavedSettings'

function readSavedSettingsIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SETTINGS_SAVED_STORAGE_KEY) ?? '[]'))
  } catch {
    return new Set()
  }
}

function hasSavedSettings(collectionId: string): boolean {
  return readSavedSettingsIds().has(collectionId)
}

// Confirmed (not just saved with defaults) at least once: that's what gates
// documents/QA/etc. on a freshly created collection, see isCollectionReady.
function markSettingsSaved(collectionId: string) {
  const ids = readSavedSettingsIds()
  ids.add(collectionId)
  localStorage.setItem(SETTINGS_SAVED_STORAGE_KEY, JSON.stringify([...ids]))
}

// A collection must be named and have its chunking/embedding parameters
// explicitly confirmed before documents (or anything else) can be added -
// this is what CollectionDetailView gates its other tabs on.
function isCollectionReady(collection: Collection): boolean {
  // A non-owner (public or shared collection) never sees the Settings tab and can't confirm
  // anything there - the "settings saved" gate only makes sense for the owner's own browser.
  if (!collection.isOwner) return true
  return collection.name.trim() !== '' && collection.name !== DEFAULT_COLLECTION_NAME && hasSavedSettings(collection.id)
}

const collections = ref<Collection[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)
const documentError = ref<string | null>(null)
const activeCollectionId = ref<string>()
const activeCollection = computed(() =>
  collections.value.find((collection) => collection.id === activeCollectionId.value),
)

async function fetchCollections() {
  isLoading.value = true
  error.value = null
  try {
    // A single generously-sized page for now: collections are still browsed
    // and paginated entirely client-side (see useCollectionsBrowser).
    const response = await fetch(`${API_BASE_URL}/api/collections?page_size=100`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { items: CollectionOut[] } = await response.json()
    // Merged, not replaced: a collection opened by URL may already have had its documents (or
    // other tabs) loaded before this first list arrives - replacing would wipe them.
    const fresh = body.items.map(toCollection)
    const freshIds = new Set(fresh.map((item) => item.id))
    collections.value = collections.value.filter((item) => freshIds.has(item.id) || item.id === activeCollectionId.value)
    fresh.forEach(upsertCollection)
  } catch {
    error.value = 'Impossible de récupérer les collections.'
  } finally {
    isLoading.value = false
  }
}

async function fetchCollection(id: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, { credentials: 'include' })
    if (!response.ok) return
    upsertCollection(toCollection(await response.json()))
  } catch {
    // Ignored: the detail view already handles a missing/unfetchable collection.
  }
}

function upsertCollection(collection: Collection) {
  if (collections.value.some((item) => item.id === collection.id)) replaceCollection(collection.id, collection)
  else collections.value.push(collection)
}

// The direct sub-collections of a collection (#215), merged into the shared list rather than kept
// apart: the list is what every view reads from, and a sub-collection may not be in its first page.
async function refreshChildren(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/children?page_size=100`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const body: { items: CollectionOut[] } = await response.json()
    body.items.map(toCollection).forEach(upsertCollection)
  } catch {
    // Ignored: the tab just keeps whatever it last had.
  }
}

// Moving or deleting a collection changes the path of everything below it (and a parent's
// children count) - reloads the list while keeping every collection's already-loaded tabs, unlike
// fetchCollections, which starts over.
async function refreshTree() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections?page_size=100`, { credentials: 'include' })
    if (!response.ok) return
    const body: { items: CollectionOut[] } = await response.json()
    const fresh = body.items.map(toCollection)
    const freshIds = new Set(fresh.map((item) => item.id))
    // Kept: anything fetched on its own (an opened sub-collection beyond the first page).
    collections.value = collections.value.filter((item) => freshIds.has(item.id) || item.id === activeCollectionId.value)
    fresh.forEach(upsertCollection)
  } catch {
    // Ignored: the list stays as it was until the next reload.
  }
}

fetchCollections()

// Maps a tab key to the function that loads its data. Each tab is fetched on
// demand (when first opened) instead of all at once on openCollection - avoids
// hammering the backend with 5 parallel requests when the user only looks at
// the Settings tab.
const TAB_LOADERS: Record<string, (id: string) => void | Promise<void>> = {
  documents: (id) => refreshDocuments(id).then(() => {
    const collection = collections.value.find((item) => item.id === id)
    const stillProcessing = collection?.documents.some(
      (document) => document.status === 'pending' || document.status === 'indexing',
    )
    if (stillProcessing) pollDocumentsWhileProcessing(id)
  }),
  qa: refreshQaPairs,
  chunks: refreshChunks,
  relations: refreshEntitiesAndRelations,
  evaluation: refreshEvaluation,
  settings: async (id) => {
    await Promise.all([refreshShares(id), refreshIndexRebuild(id)])
  },
  subcollections: refreshChildren,
}

// Tracks which tabs have already been loaded for the active collection, so
// switching back to a tab doesn't refetch (a manual refresh button can be
// added later if stale data becomes an issue).
const loadedTabs = ref<Set<string>>(new Set())

function loadTabData(collectionId: string, tab: string) {
  const key = `${collectionId}:${tab}`
  if (loadedTabs.value.has(key)) return
  loadedTabs.value.add(key)
  const loader = TAB_LOADERS[tab]
  if (loader) loader(collectionId)
}

// `navigate: false` is used when a route change already triggered this (see
// CollectionsView's route watcher) - pushing again there would just double the entry.
function openCollection(id: string, options: { navigate?: boolean; tab?: string } = {}) {
  activeCollectionId.value = id
  // Load only the data for the active tab - the rest is fetched lazily as the
  // user navigates between tabs (see loadTabData / selectTab in the detail view).
  const tab = options.tab ?? (router.currentRoute.value.params.tab as string | undefined) ?? 'settings'
  // A collection opened by URL isn't in the list yet: its tab data has nowhere to land until it is.
  if (collections.value.some((item) => item.id === id)) loadTabData(id, tab)
  else fetchCollection(id).then(() => loadTabData(id, tab))
  const target = `/collections/${id}/${tab}`
  if (options.navigate !== false && router.currentRoute.value.fullPath !== target) {
    router.push(target)
  }
}

function closeCollection(options: { navigate?: boolean } = {}) {
  activeCollectionId.value = undefined
  if (options.navigate !== false && router.currentRoute.value.path !== '/collections') {
    router.push('/collections')
  }
}

// name/description: pre-filled from an unfiled file's own name/summary when creating a
// collection straight from the filing review page's "Créer une collection" shortcut (§122
// follow-up) - omitted (defaults apply server-side) for the plain "+ Nouvelle collection" click.
// parentId: creates a sub-collection (#215), which starts from a copy of its parent's settings.
async function createCollection(name?: string, description?: string, parentId?: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, parent_id: parentId }),
  })
  if (!response.ok) return
  const collection = toCollection(await response.json())
  collections.value.unshift(collection)
  // The parent's children count just changed.
  if (parentId) fetchCollection(parentId)
  openCollection(collection.id)
}

const moveError = ref<string | null>(null)

// parentId null moves the collection back to the top level. Only between collections the user
// owns - the backend answers 404 for a parent they don't own and 409 for a cycle.
async function moveCollection(id: string, parentId: string | null): Promise<boolean> {
  moveError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_id: parentId }),
    })
    if (response.status === 409) {
      moveError.value = 'Une collection ne peut pas être déplacée dans elle-même ni dans une de ses sous-collections.'
      return false
    }
    if (!response.ok) {
      moveError.value = 'Impossible de déplacer cette collection.'
      return false
    }
    replaceCollection(id, toCollection(await response.json()))
  } catch {
    moveError.value = 'Impossible de déplacer cette collection : le serveur est inaccessible.'
    return false
  }
  await refreshTree()
  return true
}

// Every collection below `id`, at any depth, among those already loaded.
function descendantsOf(id: string): Collection[] {
  return collections.value.filter((collection) => collection.path.some((item) => item.id === id))
}

// CollectionOut doesn't embed documents/qaPairs/entities/relations/chunks/shares (see
// toCollection's comments) - every PATCH response would otherwise wipe whatever was already
// loaded for those. Carries the previous entry's sub-resources forward instead of losing them.
function replaceCollection(id: string, next: Collection) {
  const index = collections.value.findIndex((item) => item.id === id)
  if (index === -1) return
  const previous = collections.value[index]
  collections.value[index] = {
    ...next,
    documents: previous.documents,
    qaPairs: previous.qaPairs,
    entities: previous.entities,
    relations: previous.relations,
    chunks: previous.chunks,
    shares: previous.shares,
  }
}

async function patchCollection(id: string, body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) return
  replaceCollection(id, toCollection(await response.json()))
}

function updateName(id: string, name: string) {
  if (!name.trim()) return
  patchCollection(id, { name: name.trim() })
}

function updateDescription(id: string, description: string) {
  patchCollection(id, { description })
}

// Collections whose description an administrator has asked to be written from a sample of their files (#457).
const describingCollectionIds = ref<Set<string>>(new Set())
const describeError = ref<string | null>(null)

function isDescribing(collectionId: string): boolean {
  return describingCollectionIds.value.has(collectionId)
}

function setDescribing(collectionId: string, describing: boolean) {
  const next = new Set(describingCollectionIds.value)
  if (describing) next.add(collectionId)
  else next.delete(collectionId)
  describingCollectionIds.value = next
}

// The worker runs asynchronously: poll the collection until its description is written, and give up after 5 min
// (a description the model finds already right does not change - the button comes back, nothing to show).
async function generateDescription(collectionId: string) {
  if (isDescribing(collectionId)) return
  describeError.value = null
  setDescribing(collectionId, true)
  const before = collections.value.find((item) => item.id === collectionId)?.descriptionMeta?.updatedAt
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/description/generate`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) {
      describeError.value = `Échec du lancement de la description (${response.status}).`
      setDescribing(collectionId, false)
      return
    }
  } catch {
    describeError.value = 'Échec du lancement de la description : le serveur est inaccessible.'
    setDescribing(collectionId, false)
    return
  }
  for (let attempt = 0; attempt < 150; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 2000))
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}`, { credentials: 'include' })
      if (!response.ok) continue
      const updated = toCollection(await response.json())
      if (updated.descriptionMeta?.updatedAt !== before) {
        replaceCollection(collectionId, updated)
        break
      }
    } catch {
      // The next attempt tries again.
    }
  }
  setDescribing(collectionId, false)
}

function updateTags(id: string, tags: string[]) {
  patchCollection(id, { tags })
}

async function deleteCollection(id: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) return
  // Its whole subtree goes with it (#214).
  const parentId = collections.value.find((item) => item.id === id)?.parentId
  const deletedIds = new Set([id, ...descendantsOf(id).map((item) => item.id)])
  collections.value = collections.value.filter((item) => !deletedIds.has(item.id))
  if (activeCollectionId.value && deletedIds.has(activeCollectionId.value)) {
    // Back up to the parent rather than the top-level list when deleting a sub-collection.
    if (parentId) openCollection(parentId, { tab: 'subcollections' })
    else closeCollection()
  }
  if (parentId) fetchCollection(parentId)
}

const shareError = ref<string | null>(null)

async function updateVisibility(id: string, visibility: CollectionVisibility) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}/visibility`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ visibility }),
  })
  if (!response.ok) return
  replaceCollection(id, toCollection(await response.json()))
}

async function refreshShares(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const raw: ShareOut[] = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (collection) collection.shares = raw.map(toShare)
  } catch {
    // Ignored: the panel just keeps whatever it last had.
  }
}

// What is shared with: an email or a Keycloak group typed in (`identifier`), or one of the groups made in Muffin
// (`groupId`, #455). `permission` is what the share lets: read, or also change (#454).
interface ShareTarget {
  subjectType: ShareSubjectType
  identifier?: string
  groupId?: string
  permission?: SharePermission
}

// Never confirms whether `identifier` resolves to a real account/group - the invitation is
// always created PENDING and resolved passively the next time a matching user logs in (see
// backend/app/core/sharing.py). shareError surfaces only real failures (already invited,
// sharing not configured), never "does this email exist". A group made in Muffin is a known
// object, so that share is active at once.
async function createShare(collectionId: string, target: ShareTarget) {
  shareError.value = null
  const identifier = target.identifier?.trim()
  if (!identifier && !target.groupId) return
  const body: Record<string, string> = { subject_type: target.subjectType, permission: target.permission ?? 'read' }
  if (target.groupId) body.group_id = target.groupId
  else if (identifier) body.identifier = identifier
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (response.status === 409) {
      shareError.value = 'Cet email ou ce groupe est déjà invité sur cette collection.'
      return
    }
    if (response.status === 404 && target.groupId) {
      shareError.value = "Ce groupe n'existe plus ou vous n'en faites pas partie."
      return
    }
    if (response.status === 503) {
      shareError.value = "Le partage n'est pas configuré sur cet environnement."
      return
    }
    if (!response.ok) {
      shareError.value = "Échec de l'invitation."
      return
    }
  } catch {
    shareError.value = "Échec de l'invitation : le serveur est inaccessible."
    return
  }
  await refreshShares(collectionId)
}

// Lets a share read only, or also write (#454).
async function updateSharePermission(collectionId: string, shareId: string, permission: SharePermission) {
  shareError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares/${shareId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ permission }),
    })
    if (!response.ok) {
      shareError.value = 'Échec du changement de droit.'
      return
    }
  } catch {
    shareError.value = 'Échec du changement de droit : le serveur est inaccessible.'
    return
  }
  await refreshShares(collectionId)
}

async function deleteShare(collectionId: string, shareId: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares/${shareId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) return
  const collection = collections.value.find((item) => item.id === collectionId)
  if (collection) collection.shares = collection.shares.filter((share) => share.id !== shareId)
}

// Keeps the card counts in step with the documents once they're loaded.
function setDocuments(collection: Collection, documents: CollectionDocument[]) {
  collection.documents = documents
  collection.documentCount = documents.length
  collection.indexedDocumentCount = documents.filter((document) => document.status === 'indexed').length
}

// One poll loop per collection at most, stopped once nothing is pending/indexing.
const documentPolls = new Map<string, ReturnType<typeof setInterval>>()

async function refreshDocuments(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const raw: DocumentOut[] = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (!collection) return
    setDocuments(collection, raw.map(toDocument))

    const stillProcessing = collection.documents.some(
      (document) => document.status === 'pending' || document.status === 'indexing',
    )
    if (!stillProcessing) {
      const interval = documentPolls.get(collectionId)
      if (interval) clearInterval(interval)
      documentPolls.delete(collectionId)
    }
  } catch {
    // Ignored: the next poll tick (or the next manual refresh) retries.
  }
}

interface QaPairOut {
  id: string
  question: string
  answer: string
  source?: string
  source_document_id?: string | null
  source_page?: number | null
  source_excerpt?: string | null
  source_start?: number | null
  source_end?: number | null
  origin: QaPair['origin']
  validated: boolean
  golden: boolean
  relevant_documents: { id: string; name: string }[]
}

function toQaPair(raw: QaPairOut): QaPair {
  return {
    id: raw.id,
    question: raw.question,
    answer: raw.answer,
    source: raw.source ?? undefined,
    sourceDocumentId: raw.source_document_id ?? undefined,
    sourcePage: raw.source_page ?? undefined,
    sourceExcerpt: raw.source_excerpt ?? undefined,
    sourceStart: raw.source_start ?? undefined,
    sourceEnd: raw.source_end ?? undefined,
    origin: raw.origin,
    validated: raw.validated,
    golden: raw.golden,
    relevantDocuments: raw.relevant_documents ?? [],
  }
}

async function refreshQaPairs(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/qa-pairs`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const raw: QaPairOut[] = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (collection) collection.qaPairs = raw.map(toQaPair)
  } catch {
    // Ignored: the tab just keeps whatever it last had; a manual reopen retries.
  }
}

async function refreshChunks(collectionId: string) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/chunks?page_size=100`,
      { credentials: 'include' },
    )
    if (!response.ok) return
    const body: { items: Chunk[] } = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (collection) {
      collection.chunks = body.items.map((item) => ({
        id: item.id,
        documentName: (item as unknown as { document_name: string }).document_name,
        index: item.index,
        text: item.text,
        tokenCount: (item as unknown as { token_count: number }).token_count,
      }))
    }
  } catch {
    // Ignored: same as refreshQaPairs above.
  }
}

async function refreshEntitiesAndRelations(collectionId: string) {
  try {
    const [entitiesResponse, relationsResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/collections/${collectionId}/entities`, { credentials: 'include' }),
      fetch(`${API_BASE_URL}/api/collections/${collectionId}/relations`, { credentials: 'include' }),
    ])
    const collection = collections.value.find((item) => item.id === collectionId)
    if (!collection) return
    // Field names already match Entity (id/name/type/mentions) and Relation (id/from/to/type) - no mapping needed.
    if (entitiesResponse.ok) collection.entities = await entitiesResponse.json()
    if (relationsResponse.ok) collection.relations = await relationsResponse.json()
  } catch {
    // Ignored: same as refreshQaPairs above.
  }
}

// Backend EvaluationRunOut is snake_case and has validated/unvalidated breakdowns the
// frontend doesn't use yet - we map to the simpler EvaluationRun shape the UI expects.
interface EvaluationRunOut {
  id: string
  created_at: string
  k: number
  pair_count: number
  llm_model: string
  snapshot_chunking_strategy: string
  snapshot_chunk_size: number
  snapshot_chunk_overlap: number
  snapshot_embedding_model: string
  precision_at_k: number | null
  recall_at_k: number | null
  mrr: number | null
  ndcg: number | null
  golden_pair_count: number
  golden_precision_at_k: number | null
  golden_recall_at_k: number | null
  golden_mrr: number | null
  golden_ndcg: number | null
  results: {
    qa_pair_id: string | null
    golden: boolean
    question: string
    expected_answer: string
    generated_answer: string
    precision_at_k: number
    recall_at_k: number
    reciprocal_rank: number
    ndcg: number
    retrieved_sources: string[]
  }[]
}

async function refreshEvaluation(collectionId: string) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/evaluations`,
      { credentials: 'include' },
    )
    if (!response.ok) return
    const runs: EvaluationRunOut[] = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (!collection) return
    collection.evaluationRuns = runs.map((run) => ({
      id: run.id,
      runAt: run.created_at,
      k: run.k,
      pairCount: run.pair_count,
      llmModel: run.llm_model,
      chunkingSnapshot: {
        strategy: run.snapshot_chunking_strategy as ChunkStrategy,
        chunkSize: run.snapshot_chunk_size,
        chunkOverlap: run.snapshot_chunk_overlap,
        embeddingModel: run.snapshot_embedding_model,
      },
      metrics:
        run.precision_at_k === null || run.recall_at_k === null || run.mrr === null || run.ndcg === null
          ? null
          : { precisionAtK: run.precision_at_k, recallAtK: run.recall_at_k, mrr: run.mrr, ndcg: run.ndcg },
      goldenMetrics:
        run.golden_pair_count > 0 &&
        run.golden_precision_at_k !== null &&
        run.golden_recall_at_k !== null &&
        run.golden_mrr !== null &&
        run.golden_ndcg !== null
          ? {
              pairCount: run.golden_pair_count,
              precisionAtK: run.golden_precision_at_k,
              recallAtK: run.golden_recall_at_k,
              mrr: run.golden_mrr,
              ndcg: run.golden_ndcg,
            }
          : null,
      results: run.results.map((result) => ({
        qaPairId: result.qa_pair_id ?? '',
        question: result.question,
        expectedAnswer: result.expected_answer,
        generatedAnswer: result.generated_answer,
        retrievedSources: result.retrieved_sources,
        precisionAtK: result.precision_at_k,
        recallAtK: result.recall_at_k,
        reciprocalRank: result.reciprocal_rank,
        ndcg: result.ndcg,
        golden: result.golden,
      })),
    }))
  } catch {
    // Ignored: same as refreshQaPairs above.
  }
}

function pollDocumentsWhileProcessing(collectionId: string) {
  if (documentPolls.has(collectionId)) return
  documentPolls.set(
    collectionId,
    setInterval(() => refreshDocuments(collectionId), 2000),
  )
}

// What the backend refused as already in the collection (#300), waiting for the user to say whether to add
// it anyway: the file or the URL, and the name of the document that is already there.
export type PendingDuplicate =
  | { kind: 'file'; collectionId: string; file: File; existingName: string }
  | { kind: 'url'; collectionId: string; url: string; schedule: RefreshSchedule | null; existingName: string }

const pendingDuplicates = ref<PendingDuplicate[]>([])

// The name of the document a 409 `duplicate_document` says is already there, or null for any other answer.
async function existingNameOf(response: Response): Promise<string | null> {
  if (response.status !== 409) return null
  try {
    const detail = (await response.json())?.detail
    return detail?.code === 'duplicate_document' ? String(detail.document?.name ?? '') : null
  } catch {
    return null
  }
}

async function uploadFile(collectionId: string, file: File, allowDuplicate: boolean) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/documents/file${allowDuplicate ? '?allow_duplicate=true' : ''}`,
      { method: 'POST', credentials: 'include', body: formData },
    )
    const existingName = await existingNameOf(response)
    if (existingName !== null) {
      pendingDuplicates.value = [...pendingDuplicates.value, { kind: 'file', collectionId, file, existingName }]
    } else if (response.status === 413) {
      // Only when the server sets a maximum size (DOCUMENT_MAX_UPLOAD_BYTES): there is none by default.
      documentError.value = `« ${file.name} » dépasse la taille maximale acceptée par le serveur.`
    } else if (!response.ok) {
      documentError.value = `Échec de l'envoi de « ${file.name} » (${response.status}).`
    }
  } catch {
    documentError.value = `Échec de l'envoi de « ${file.name} » : le serveur est inaccessible.`
  }
}

async function addDocuments(collectionId: string, files: File[]) {
  documentError.value = null
  for (const file of files) await uploadFile(collectionId, file, false)
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

// The user confirmed: what was refused as a duplicate of this collection is added anyway.
async function confirmDuplicates(collectionId: string) {
  const mine = pendingDuplicates.value.filter((duplicate) => duplicate.collectionId === collectionId)
  pendingDuplicates.value = pendingDuplicates.value.filter((duplicate) => duplicate.collectionId !== collectionId)
  documentError.value = null
  for (const duplicate of mine) {
    if (duplicate.kind === 'file') await uploadFile(collectionId, duplicate.file, true)
    else await postUrl(collectionId, duplicate.url, duplicate.schedule, true)
  }
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

function dismissDuplicates(collectionId: string) {
  pendingDuplicates.value = pendingDuplicates.value.filter((duplicate) => duplicate.collectionId !== collectionId)
}

// Same flow as addDocuments, against the living-document endpoint (ODT/Markdown only, the
// backend answers 415 for anything else) - one request per file, errors surfaced via documentError.
async function addLivingDocuments(collectionId: string, files: File[]) {
  documentError.value = null
  for (const file of files) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/living`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (response.status === 415) {
        documentError.value = `« ${file.name} » n'est pas un document vivant : seuls les fichiers .odt et .md sont acceptés.`
      } else if (!response.ok) {
        documentError.value = `Échec de l'envoi de « ${file.name} » (${response.status}).`
      }
    } catch {
      documentError.value = `Échec de l'envoi de « ${file.name} » : le serveur est inaccessible.`
    }
  }
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

// A Markdown living document written from scratch in the UI (no file to upload). Resolves to
// whether it was created - the caller keeps its form open on a failure, with documentError set.
async function createMarkdownDocument(collectionId: string, name: string, content: string): Promise<boolean> {
  documentError.value = null
  let created = false
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/living/markdown`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, content }),
    })
    created = response.ok
    if (!response.ok) documentError.value = `Échec de la création du document (${response.status}).`
  } catch {
    documentError.value = 'Échec de la création du document : le serveur est inaccessible.'
  }
  if (created) {
    await refreshDocuments(collectionId)
    pollDocumentsWhileProcessing(collectionId)
  }
  return created
}

// Re-reads the list and restarts the processing poll - for callers that changed a document
// outside this composable (e.g. a living document replaced from its revisions panel).
async function reloadDocuments(collectionId: string) {
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

async function postUrl(
  collectionId: string,
  url: string,
  refreshSchedule: RefreshSchedule | null,
  allowDuplicate: boolean,
) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/url`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.trim(), refresh_schedule: refreshSchedule, allow_duplicate: allowDuplicate }),
    })
    const existingName = await existingNameOf(response)
    if (existingName !== null) {
      pendingDuplicates.value = [
        ...pendingDuplicates.value,
        { kind: 'url', collectionId, url: url.trim(), schedule: refreshSchedule, existingName },
      ]
    } else if (!response.ok) {
      documentError.value = `Échec de l'ajout de l'URL (${response.status}).`
    }
  } catch {
    documentError.value = "Échec de l'ajout de l'URL : le serveur est inaccessible."
  }
}

async function addUrl(collectionId: string, url: string, refreshSchedule: RefreshSchedule | null = null) {
  if (!url.trim()) return
  documentError.value = null
  await postUrl(collectionId, url, refreshSchedule, false)
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

async function removeDocument(collectionId: string, documentId: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) return
  const collection = collections.value.find((item) => item.id === collectionId)
  if (collection) setDocuments(collection, collection.documents.filter((item) => item.id !== documentId))
}

// Relaunching the indexing of documents that ended in error (#340). The documents are read again, which
// shows them back as waiting, and polled until they are done. Both resolve to how many were relaunched -
// null when it failed (documentError says why).
async function reprocessDocument(collectionId: string, documentId: string): Promise<boolean> {
  documentError.value = null
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}/reprocess`,
      { method: 'POST', credentials: 'include' },
    )
    if (!response.ok) {
      documentError.value =
        response.status === 409
          ? "Ce document n'est plus en erreur : il n'a pas été relancé."
          : `Impossible de relancer l'indexation (${response.status}).`
      return false
    }
  } catch {
    documentError.value = "Impossible de relancer l'indexation : le serveur est injoignable."
    return false
  }
  await reloadDocuments(collectionId)
  return true
}

async function reprocessFailedDocuments(collectionId: string): Promise<number | null> {
  documentError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/reprocess-failed`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) {
      documentError.value = `Impossible de relancer l'indexation (${response.status}).`
      return null
    }
    const body: { reprocessed: number } = await response.json()
    await reloadDocuments(collectionId)
    return body.reprocessed
  } catch {
    documentError.value = "Impossible de relancer l'indexation : le serveur est injoignable."
    return null
  }
}

const qaError = ref<string | null>(null)

function qaUrl(collectionId: string, suffix = ''): string {
  return `${API_BASE_URL}/api/collections/${collectionId}/qa-pairs${suffix}`
}

// A pair written by hand, saved on the backend: a reference the assistant answers from, or - `golden` -
// a test question that is never in the retriever and only measures it (#260). Resolves to whether it
// was saved, so the form keeps what was typed on a failure (qaError says why).
async function addQaPair(
  collectionId: string,
  question: string,
  answer: string,
  options: { golden?: boolean; relevantDocumentIds?: string[] } = {},
): Promise<boolean> {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection || !question.trim() || !answer.trim()) return false
  qaError.value = null
  try {
    const response = await fetch(qaUrl(collectionId), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: question.trim(),
        answer: answer.trim(),
        golden: options.golden ?? false,
        relevant_document_ids: options.relevantDocumentIds ?? [],
      }),
    })
    if (!response.ok) {
      qaError.value = `La question n'a pas pu être enregistrée (${response.status}).`
      return false
    }
    collection.qaPairs.unshift(toQaPair(await response.json()))
    collection.updatedAt = new Date().toISOString()
    return true
  } catch {
    qaError.value = 'La question n’a pas pu être enregistrée : le serveur est inaccessible.'
    return false
  }
}

async function removeQaPair(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  qaError.value = null
  try {
    const response = await fetch(qaUrl(collectionId, `/${qaPairId}`), { method: 'DELETE', credentials: 'include' })
    if (!response.ok && response.status !== 404) {
      qaError.value = `La question n'a pas pu être retirée (${response.status}).`
      return
    }
    collection.qaPairs = collection.qaPairs.filter((item) => item.id !== qaPairId)
  } catch {
    qaError.value = 'La question n’a pas pu être retirée : le serveur est inaccessible.'
  }
}

async function toggleQaValidation(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  const pair = collection?.qaPairs.find((item) => item.id === qaPairId)
  if (!pair || pair.golden) return
  qaError.value = null
  try {
    const response = await fetch(qaUrl(collectionId, `/${qaPairId}`), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ validated: !pair.validated }),
    })
    if (!response.ok) {
      qaError.value = `La validation n'a pas pu être enregistrée (${response.status}).`
      return
    }
    pair.validated = !pair.validated
  } catch {
    qaError.value = 'La validation n’a pas pu être enregistrée : le serveur est inaccessible.'
  }
}

async function patchSettings(id: string, body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}/settings`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) return
  replaceCollection(id, toCollection(await response.json()))
}

async function updateChunkingSettings(collectionId: string, settings: ChunkingSettings) {
  await patchSettings(collectionId, {
    chunking_strategy: settings.strategy,
    chunk_size: settings.chunkSize,
    chunk_overlap: settings.chunkOverlap,
  })
}

// Changer de modèle d'embedding invalide les vecteurs déjà calculés - le
// backend détecte ce changement et positionne reindexRequired lui-même.
async function updateEmbeddingModel(collectionId: string, model: string) {
  await patchSettings(collectionId, { embedding_model: model })
}

async function updateGenerationModel(collectionId: string, field: keyof GenerationModels, model: string) {
  await patchSettings(collectionId, { generation_models: { [field]: model } })
}

const PIPELINE_WINDOW_KEYS: Record<keyof PipelineWindows, string> = {
  summaryPagesPerMap: 'summary_pages_per_map',
  qaWindowPages: 'qa_window_pages',
  qaSlidePages: 'qa_slide_pages',
  qaQuestionsPerWindow: 'qa_questions_per_window',
  extractionWindowPages: 'extraction_window_pages',
  extractionSlidePages: 'extraction_slide_pages',
  chunkingWindowPages: 'chunking_window_pages',
  chunkingSlidePages: 'chunking_slide_pages',
  collectionQaCount: 'collection_qa_count',
  samplingMinPages: 'sampling_min_pages',
  summaryMode: 'summary_mode',
  summaryPercent: 'summary_percent',
  summaryHeadPercent: 'summary_head_percent',
  summaryTailPercent: 'summary_tail_percent',
  summaryPageRanges: 'summary_page_ranges',
  qaMaxQuestions: 'qa_max_questions',
  extractionPercent: 'extraction_percent',
  extractionMaxWindows: 'extraction_max_windows',
}

async function updatePipelineWindows(collectionId: string, values: Partial<PipelineWindows>) {
  const pipeline_windows: Record<string, number | string | null> = {}
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) pipeline_windows[PIPELINE_WINDOW_KEYS[key as keyof PipelineWindows]] = value
  }
  await patchSettings(collectionId, { pipeline_windows })
}

// Le backend refuse les valeurs qui n'ont pas de sens avec un message lisible (422) : on le rend tel quel.
async function errorOf(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // pas de corps lisible : le message générique ci-dessous
  }
  return `Le serveur a répondu ${response.status}.`
}

// Enregistre tous les réglages d'un coup (une seule requête) ; renvoie le message du refus, ou null une fois
// enregistré. Les réglages sont alors confirmés : la collection peut recevoir des documents.
async function saveCollectionSettings(collectionId: string, patch: SettingsPatch): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/settings`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!response.ok) return await errorOf(response)
    markSettingsSaved(collectionId)
    replaceCollection(collectionId, toCollection(await response.json()))
    return null
  } catch {
    return 'Les réglages n’ont pas pu être enregistrés : le serveur est inaccessible.'
  }
}

interface IndexingEstimateOut {
  pages: number
  sampled: boolean
  chat: Record<string, number>
  embeddings: Record<string, number>
  collection_max: number
}

// Les appels au modèle que coûterait un document de `pages` pages avec ces réglages, tapés et pas encore
// enregistrés (rien n'est stocké) ; sans réglages, ceux de la collection.
async function estimateIndexing(
  collectionId: string,
  pages: number,
  pipelineWindows: Partial<LongDocumentsPayload> = {},
  chunkingStrategy?: string,
): Promise<{ estimate: IndexingEstimate } | { error: string }> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/indexing-estimate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pages, pipeline_windows: pipelineWindows, chunking_strategy: chunkingStrategy }),
    })
    if (!response.ok) return { error: await errorOf(response) }
    const raw: IndexingEstimateOut = await response.json()
    return {
      estimate: {
        pages: raw.pages,
        sampled: raw.sampled,
        chat: raw.chat,
        embeddings: raw.embeddings,
        collectionMax: raw.collection_max,
      },
    }
  } catch {
    return { error: 'L’estimation est indisponible : le serveur est inaccessible.' }
  }
}

interface IndexRebuildOut {
  id: string
  status: IndexRebuild['status']
  target_model: string
  previous_model: string
  total_points: number
  done_points: number
  error: string | null
}

function toIndexRebuild(raw: IndexRebuildOut): IndexRebuild {
  return {
    id: raw.id,
    status: raw.status,
    targetModel: raw.target_model,
    previousModel: raw.previous_model,
    totalPoints: raw.total_points,
    donePoints: raw.done_points,
    error: raw.error,
  }
}

// The latest blue/green rebuild of each collection's index (#12), null when it never had one.
const indexRebuilds = ref<Record<string, IndexRebuild | null>>({})
const indexRebuildError = ref<string | null>(null)
const indexRebuildPolls = new Map<string, ReturnType<typeof setInterval>>()

async function refreshIndexRebuild(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/index-rebuild`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const raw: IndexRebuildOut | null = await response.json()
    const previous = indexRebuilds.value[collectionId]
    const rebuild = raw ? toIndexRebuild(raw) : null
    indexRebuilds.value[collectionId] = rebuild
    if (rebuild?.status === 'building') {
      pollIndexRebuild(collectionId)
      return
    }
    stopPollingIndexRebuild(collectionId)
    // The swap (or a failure) changed which model the index holds: reflected in the collection.
    if (previous?.status === 'building') await fetchCollection(collectionId)
  } catch {
    // Ignored: the next poll tick (or the next manual refresh) retries.
  }
}

function pollIndexRebuild(collectionId: string) {
  if (indexRebuildPolls.has(collectionId)) return
  indexRebuildPolls.set(
    collectionId,
    setInterval(() => refreshIndexRebuild(collectionId), 3000),
  )
}

function stopPollingIndexRebuild(collectionId: string) {
  const interval = indexRebuildPolls.get(collectionId)
  if (interval) clearInterval(interval)
  indexRebuildPolls.delete(collectionId)
}

// Starts the blue/green rebuild: search keeps using the current index until the new one is complete.
async function reindexCollection(collectionId: string) {
  indexRebuildError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/reindex`, {
      method: 'POST',
      credentials: 'include',
    })
    if (response.status === 409) {
      indexRebuildError.value = 'Une réindexation est déjà en cours pour cette collection.'
    } else if (!response.ok) {
      indexRebuildError.value = `Échec du lancement de la réindexation (${response.status}).`
    }
  } catch {
    indexRebuildError.value = 'Échec du lancement de la réindexation : le serveur est inaccessible.'
  }
  await refreshIndexRebuild(collectionId)
}

// Validating deletes the old index kept since the swap; rolling back returns to it (and its model).
async function settleIndexRebuild(collectionId: string, action: 'finalize' | 'rollback') {
  const rebuild = indexRebuilds.value[collectionId]
  if (!rebuild) return
  indexRebuildError.value = null
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/index-rebuild/${rebuild.id}/${action}`,
      { method: 'POST', credentials: 'include' },
    )
    if (!response.ok) indexRebuildError.value = `Échec de l'opération (${response.status}).`
  } catch {
    indexRebuildError.value = "Échec de l'opération : le serveur est inaccessible."
  }
  await refreshIndexRebuild(collectionId)
  await fetchCollection(collectionId)
}

const finalizeIndexRebuild = (collectionId: string) => settleIndexRebuild(collectionId, 'finalize')
const rollbackIndexRebuild = (collectionId: string) => settleIndexRebuild(collectionId, 'rollback')

async function updateInstructionField(collectionId: string, field: keyof PipelineInstructions, value: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  // The backend expects the whole PipelineInstructions object, not a patch of
  // one field - send the current one with just this field changed.
  await patchSettings(collectionId, { instructions: { ...collection.instructions, [field]: value } })
}

const EVAL_K = 5

// Tracks active evaluation polls so a second click doesn't start a duplicate interval.
const evaluationPolls = new Map<string, ReturnType<typeof setInterval>>()
// Reactive set of collection IDs currently running an evaluation.
const evaluatingCollectionIds = ref<Set<string>>(new Set())

function isEvaluating(collectionId: string): boolean {
  return evaluatingCollectionIds.value.has(collectionId)
}

async function runEvaluation(collectionId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return

  if (isEvaluating(collectionId)) return

  // Evaluate all QA pairs with a source document, not just validated ones - the run's
  // validated/unvalidated breakdown still separates them in the results.
  const evaluable = collection.qaPairs.filter((pair) => pair.source)
  if (!evaluable.length) return

  evaluatingCollectionIds.value.add(collectionId)
  // Trigger reactivity for the Set mutation
  evaluatingCollectionIds.value = new Set(evaluatingCollectionIds.value)

  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/evaluations`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ k: EVAL_K, validated_only: false }),
    })
    if (!response.ok) {
      evaluatingCollectionIds.value.delete(collectionId)
      evaluatingCollectionIds.value = new Set(evaluatingCollectionIds.value)
      return
    }
  } catch {
    evaluatingCollectionIds.value.delete(collectionId)
    evaluatingCollectionIds.value = new Set(evaluatingCollectionIds.value)
    return
  }

  // The worker runs asynchronously (Celery queue "evaluation"); poll until the
  // new run appears in the list, mirroring pollDocumentsWhileProcessing.
  pollEvaluationWhileRunning(collectionId)
}

function pollEvaluationWhileRunning(collectionId: string) {
  if (evaluationPolls.has(collectionId)) return
  const previousRunCount = collections.value.find((item) => item.id === collectionId)?.evaluationRuns.length ?? 0
  let attempts = 0
  const maxAttempts = 150 // 5 min at 2s intervals
  evaluationPolls.set(
    collectionId,
    setInterval(async () => {
      attempts++
      await refreshEvaluation(collectionId)
      const collection = collections.value.find((item) => item.id === collectionId)
      const currentRuns = collection?.evaluationRuns ?? []
      if (currentRuns.length > previousRunCount || attempts >= maxAttempts) {
        const handle = evaluationPolls.get(collectionId)
        if (handle) {
          clearInterval(handle)
          evaluationPolls.delete(collectionId)
        }
        evaluatingCollectionIds.value.delete(collectionId)
        evaluatingCollectionIds.value = new Set(evaluatingCollectionIds.value)
      }
    }, 2000),
  )
}

async function deleteEvaluation(collectionId: string, runId: string) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/evaluations/${runId}`,
      { method: 'DELETE', credentials: 'include' },
    )
    if (!response.ok) return
  } catch {
    return
  }
  const collection = collections.value.find((item) => item.id === collectionId)
  if (collection) {
    collection.evaluationRuns = collection.evaluationRuns.filter((run) => run.id !== runId)
  }
}

export function useCollections() {
  return {
    collections,
    isLoading,
    error,
    documentError,
    activeCollection,
    isCollectionReady,
    markSettingsSaved,
    refresh: fetchCollections,
    openCollection,
    closeCollection,
    createCollection,
    updateName,
    updateDescription,
    generateDescription,
    isDescribing,
    describeError,
    updateTags,
    deleteCollection,
    moveCollection,
    moveError,
    descendantsOf,
    refreshChildren,
    shareError,
    updateVisibility,
    refreshShares,
    createShare,
    updateSharePermission,
    deleteShare,
    addDocuments,
    addLivingDocuments,
    createMarkdownDocument,
    reloadDocuments,
    addUrl,
    pendingDuplicates,
    confirmDuplicates,
    dismissDuplicates,
    removeDocument,
    reprocessDocument,
    reprocessFailedDocuments,
    addQaPair,
    removeQaPair,
    toggleQaValidation,
    qaError,
    refreshQaPairs,
    refreshChunks,
    refreshEntitiesAndRelations,
    refreshEvaluation,
    loadTabData,
    updateChunkingSettings,
    updateEmbeddingModel,
    updateGenerationModel,
    updatePipelineWindows,
    saveCollectionSettings,
    hasSavedSettings,
    estimateIndexing,
    reindexCollection,
    indexRebuilds,
    indexRebuildError,
    refreshIndexRebuild,
    finalizeIndexRebuild,
    rollbackIndexRebuild,
    updateInstructionField,
    runEvaluation,
    isEvaluating,
    deleteEvaluation,
  }
}
