import { computed, ref } from 'vue'
import { router } from '../router'
import type {
  ChunkingSettings,
  ChunkStrategy,
  Chunk,
  Collection,
  CollectionDocument,
  CollectionVisibility,
  Entity,
  EvaluationRun,
  FieldStamp,
  GenerationModels,
  PipelineInstructions,
  PipelineWindows,
  QaPair,
  Relation,
  Share,
  ShareSubjectType,
} from '../types/collection'

function qa(
  question: string,
  answer: string,
  opts: { source?: string; origin?: QaPair['origin']; validated?: boolean } = {},
): QaPair {
  return {
    id: crypto.randomUUID(),
    question,
    answer,
    source: opts.source,
    origin: opts.origin ?? 'generated',
    validated: opts.validated ?? false,
  }
}

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
  documents: CollectionDocument[]
  qa_pairs: QaPair[]
  entities: Entity[]
  relations: Relation[]
  chunks: Chunk[]
  evaluation_runs: EvaluationRun[]
  chunking_settings: { strategy: ChunkingSettings['strategy']; chunk_size: number; chunk_overlap: number }
  embedding_model: string
  reindex_required: boolean
  instructions: PipelineInstructions
  generation_models: GenerationModels
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
    reindexRequired: raw.reindex_required,
    instructions: raw.instructions,
    generationModels: raw.generation_models,
    pipelineWindows: toPipelineWindows(raw.pipeline_windows),
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
  display_hint: string
  created_at: string
}

function toShare(raw: ShareOut): Share {
  return { id: raw.id, subjectType: raw.subject_type, status: raw.status, displayHint: raw.display_hint, createdAt: raw.created_at }
}

interface DocumentOut {
  id: string
  name: string
  type: CollectionDocument['type']
  status: CollectionDocument['status']
  progress: number
}

function toDocument(raw: DocumentOut): CollectionDocument {
  return { id: raw.id, name: raw.name, type: raw.type, status: raw.status, progress: raw.progress }
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
    collections.value = body.items.map(toCollection)
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
    const collection = toCollection(await response.json())
    if (collections.value.some((item) => item.id === id)) replaceCollection(id, collection)
    else collections.value.push(collection)
  } catch {
    // Ignored: the detail view already handles a missing/unfetchable collection.
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
  settings: refreshShares,
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
  if (!collections.value.some((item) => item.id === id)) fetchCollection(id)
  // Load only the data for the active tab - the rest is fetched lazily as the
  // user navigates between tabs (see loadTabData / selectTab in the detail view).
  const tab = options.tab ?? (router.currentRoute.value.params.tab as string | undefined) ?? 'settings'
  loadTabData(id, tab)
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

async function createCollection() {
  const response = await fetch(`${API_BASE_URL}/api/collections`, { method: 'POST', credentials: 'include' })
  if (!response.ok) return
  const collection = toCollection(await response.json())
  collections.value.unshift(collection)
  openCollection(collection.id)
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

function updateTags(id: string, tags: string[]) {
  patchCollection(id, { tags })
}

async function deleteCollection(id: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) return
  collections.value = collections.value.filter((item) => item.id !== id)
  if (activeCollectionId.value === id) closeCollection()
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

// Never confirms whether `identifier` resolves to a real account/group - the invitation is
// always created PENDING and resolved passively the next time a matching user logs in (see
// backend/app/core/sharing.py). shareError surfaces only real failures (already invited,
// sharing not configured), never "does this email exist".
async function createShare(collectionId: string, subjectType: ShareSubjectType, identifier: string) {
  shareError.value = null
  if (!identifier.trim()) return
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject_type: subjectType, identifier: identifier.trim() }),
    })
    if (response.status === 409) {
      shareError.value = 'Cet email ou ce groupe est déjà invité sur cette collection.'
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

async function deleteShare(collectionId: string, shareId: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/shares/${shareId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) return
  const collection = collections.value.find((item) => item.id === collectionId)
  if (collection) collection.shares = collection.shares.filter((share) => share.id !== shareId)
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
    collection.documents = raw.map(toDocument)

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

async function refreshQaPairs(collectionId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/qa-pairs`, {
      credentials: 'include',
    })
    if (!response.ok) return
    // Field names already match QaPair (id/question/answer/source/origin/validated) - no mapping needed.
    const raw: QaPair[] = await response.json()
    const collection = collections.value.find((item) => item.id === collectionId)
    if (collection) collection.qaPairs = raw
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
  precision_at_k: number
  recall_at_k: number
  mrr: number
  ndcg: number
  results: {
    qa_pair_id: string | null
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
      metrics: {
        precisionAtK: run.precision_at_k,
        recallAtK: run.recall_at_k,
        mrr: run.mrr,
        ndcg: run.ndcg,
      },
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

async function addDocuments(collectionId: string, files: File[]) {
  documentError.value = null
  for (const file of files) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/file`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      if (!response.ok) documentError.value = `Échec de l'envoi de « ${file.name} » (${response.status}).`
    } catch {
      documentError.value = `Échec de l'envoi de « ${file.name} » : le serveur est inaccessible.`
    }
  }
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

async function addUrl(collectionId: string, url: string) {
  if (!url.trim()) return
  documentError.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/url`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.trim() }),
    })
    if (!response.ok) documentError.value = `Échec de l'ajout de l'URL (${response.status}).`
  } catch {
    documentError.value = "Échec de l'ajout de l'URL : le serveur est inaccessible."
  }
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
  if (collection) collection.documents = collection.documents.filter((item) => item.id !== documentId)
}

function addQaPair(collectionId: string, question: string, answer: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection || !question.trim() || !answer.trim()) return
  // Écrite à la main dans l'UI : considérée validée d'office, pas de source document.
  collection.qaPairs.push(qa(question.trim(), answer.trim(), { origin: 'manual', validated: true }))
  collection.updatedAt = new Date().toISOString()
}

function removeQaPair(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.qaPairs = collection.qaPairs.filter((item) => item.id !== qaPairId)
}

function toggleQaValidation(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  const pair = collection?.qaPairs.find((item) => item.id === qaPairId)
  if (!pair) return
  pair.validated = !pair.validated
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
}

async function updatePipelineWindows(collectionId: string, values: Partial<PipelineWindows>) {
  const pipeline_windows: Record<string, number> = {}
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) pipeline_windows[PIPELINE_WINDOW_KEYS[key as keyof PipelineWindows]] = value
  }
  await patchSettings(collectionId, { pipeline_windows })
}

async function reindexCollection(collectionId: string) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/documents/reindex`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!response.ok) return
  const collection = collections.value.find((item) => item.id === collectionId)
  if (collection) collection.reindexRequired = false
  await refreshDocuments(collectionId)
  pollDocumentsWhileProcessing(collectionId)
}

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

async function runEvaluation(collectionId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return

  const validated = collection.qaPairs.filter((pair) => pair.validated)
  if (!validated.length) return

  try {
    const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/evaluations`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ k: EVAL_K }),
    })
    if (!response.ok) return
  } catch {
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
      }
    }, 2000),
  )
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
    updateTags,
    deleteCollection,
    shareError,
    updateVisibility,
    refreshShares,
    createShare,
    deleteShare,
    addDocuments,
    addUrl,
    removeDocument,
    addQaPair,
    removeQaPair,
    toggleQaValidation,
    refreshQaPairs,
    refreshChunks,
    refreshEntitiesAndRelations,
    refreshEvaluation,
    loadTabData,
    updateChunkingSettings,
    updateEmbeddingModel,
    updateGenerationModel,
    updatePipelineWindows,
    reindexCollection,
    updateInstructionField,
    runEvaluation,
  }
}
