import { computed, ref } from 'vue'
import { router } from '../router'
import type {
  ChunkingSettings,
  Chunk,
  Collection,
  CollectionDocument,
  Entity,
  EvaluationResult,
  EvaluationRun,
  FieldStamp,
  GenerationModels,
  PipelineInstructions,
  PipelineWindows,
  QaPair,
  Relation,
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
  }
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
    const index = collections.value.findIndex((item) => item.id === id)
    if (index === -1) collections.value.push(collection)
    else collections.value[index] = collection
  } catch {
    // Ignored: the detail view already handles a missing/unfetchable collection.
  }
}

fetchCollections()

// `navigate: false` is used when a route change already triggered this (see
// CollectionsView's route watcher) - pushing again there would just double the entry.
function openCollection(id: string, options: { navigate?: boolean } = {}) {
  activeCollectionId.value = id
  if (!collections.value.some((item) => item.id === id)) fetchCollection(id)
  // CollectionOut doesn't embed documents (avoids an N+1 on every list/get) -
  // always fetched separately, and polling resumes here in case processing
  // was still running when the collection was last closed.
  refreshDocuments(id).then(() => {
    const collection = collections.value.find((item) => item.id === id)
    const stillProcessing = collection?.documents.some(
      (document) => document.status === 'pending' || document.status === 'indexing',
    )
    if (stillProcessing) pollDocumentsWhileProcessing(id)
  })
  const target = `/collections/${id}`
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

async function patchCollection(id: string, body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE_URL}/api/collections/${id}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) return
  const collection = toCollection(await response.json())
  const index = collections.value.findIndex((item) => item.id === id)
  if (index !== -1) collections.value[index] = collection
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
  const collection = toCollection(await response.json())
  const index = collections.value.findIndex((item) => item.id === id)
  if (index !== -1) collections.value[index] = collection
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

// Pas de backend : score chaque Q/R validée avec des valeurs plausibles au
// lieu d'interroger le vrai pipeline de retrieval. Les non-validées sont
// exclues, sur demande explicite - une paire pas encore relue par un humain
// ne doit pas fausser une mesure de qualité.
const EVAL_K = 5
// Pas encore de champ dans l'UI pour choisir le modèle de génération : fixé
// ici en attendant, mais déjà tracé par run pour comparer plusieurs modèles
// plus tard sans perdre l'historique des runs passés.
const EVAL_LLM_MODEL = 'gpt-4o-mini'

function mockGeneratedAnswer(pair: QaPair): string {
  // ~1 run sur 5 simule une réponse dégradée, pour que l'écran d'évaluation
  // montre autre chose qu'un alignement parfait entre réponse générée et attendue.
  return Math.random() < 0.2
    ? "Je n'ai pas trouvé d'information suffisamment fiable pour répondre avec certitude."
    : pair.answer
}

function mockRetrievedSources(collection: Collection, pair: QaPair): string[] {
  const others = collection.documents.map((document) => document.name).filter((name) => name !== pair.source)
  const extra = others[Math.floor(Math.random() * others.length)]
  return [pair.source, extra].filter((name): name is string => Boolean(name))
}

function runEvaluation(collectionId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return

  const validated = collection.qaPairs.filter((pair) => pair.validated)
  if (!validated.length) return

  const results: EvaluationResult[] = validated.map((pair) => {
    const precisionAtK = Math.round((0.6 + Math.random() * 0.4) * 100) / 100
    const recallAtK = Math.round((0.55 + Math.random() * 0.45) * 100) / 100
    const reciprocalRank = Math.round((0.5 + Math.random() * 0.5) * 100) / 100
    const ndcg = Math.round((0.6 + Math.random() * 0.4) * 100) / 100
    return {
      qaPairId: pair.id,
      question: pair.question,
      expectedAnswer: pair.answer,
      generatedAnswer: mockGeneratedAnswer(pair),
      retrievedSources: mockRetrievedSources(collection, pair),
      precisionAtK,
      recallAtK,
      reciprocalRank,
      ndcg,
    }
  })

  const average = (values: number[]) =>
    Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100

  const run: EvaluationRun = {
    id: crypto.randomUUID(),
    runAt: new Date().toISOString(),
    k: EVAL_K,
    pairCount: results.length,
    llmModel: EVAL_LLM_MODEL,
    // Copie indépendante : si la config change après coup, ce run garde la
    // trace de ce qui a réellement produit ces résultats.
    chunkingSnapshot: { ...collection.chunkingSettings, embeddingModel: collection.embeddingModel },
    metrics: {
      precisionAtK: average(results.map((result) => result.precisionAtK)),
      recallAtK: average(results.map((result) => result.recallAtK)),
      mrr: average(results.map((result) => result.reciprocalRank)),
      ndcg: average(results.map((result) => result.ndcg)),
    },
    results,
  }

  collection.evaluationRuns.unshift(run)
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
    addDocuments,
    addUrl,
    removeDocument,
    addQaPair,
    removeQaPair,
    toggleQaValidation,
    updateChunkingSettings,
    updateEmbeddingModel,
    updateGenerationModel,
    updatePipelineWindows,
    reindexCollection,
    updateInstructionField,
    runEvaluation,
  }
}
