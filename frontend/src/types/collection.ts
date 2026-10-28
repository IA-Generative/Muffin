export interface CollectionDocument {
  id: string
  name: string
  type: 'file' | 'url'
  // 'living' = an ODT/Markdown document with a revision history (#174), replaced rather than
  // deleted and re-uploaded.
  kind: 'standard' | 'living'
  status: 'pending' | 'indexing' | 'indexed' | 'error'
  progress: number
}

// A blue/green rebuild of a collection's search index (#12): the current index keeps answering while
// the new one is built; once swapped in, the old one is kept until the owner validates or rolls back.
export interface IndexRebuild {
  id: string
  status: 'building' | 'swapped' | 'finalized' | 'rolled_back' | 'failed'
  targetModel: string
  previousModel: string
  totalPoints: number
  donePoints: number
  error: string | null
}

export interface FieldStamp {
  updatedBy: string
  updatedAt: string
}

export interface QaPair {
  id: string
  question: string
  answer: string
  source?: string
  // Where the answer comes from (#349): what opens the document on that page with the passage
  // highlighted. Absent for a pair written by hand, or one whose passage was not found.
  sourceDocumentId?: string
  sourcePage?: number
  sourceExcerpt?: string
  // Where that passage is in the page's text, when known (#351): highlighted and framed exactly.
  sourceStart?: number
  sourceEnd?: number
  origin: 'generated' | 'manual'
  validated: boolean
  // A test question (#260): written by a person, kept out of the retriever (the assistant never
  // answers from it), only used to measure the retrieval. Always validated.
  golden: boolean
  // The documents that hold the answer (a golden pair) - what retrieval is scored against.
  relevantDocuments: { id: string; name: string }[]
}

export type EntityType = 'personne' | 'organisation' | 'lieu' | 'date' | 'autre'

export interface Entity {
  id: string
  name: string
  type: EntityType
  mentions: number
  // How many occurrences were found in the text (#352) - what can be opened and framed. 0: the model listed the
  // entity but its name is nowhere in the text as written. Absent from an older answer of the API.
  occurrences?: number
}

export interface Relation {
  id: string
  from: string
  to: string
  type: string
  // The sentence that justifies the relation and where it is (#352) - as the API gives it. Absent when it has
  // none: a relation from before, or one whose sentence was not found in the text.
  source?: {
    document_id: string
    document_name: string
    page_number: number
    passage: string
    start?: number | null
    end?: number | null
  } | null
}

export interface Chunk {
  id: string
  documentName: string
  index: number
  text: string
  tokenCount: number
}

export type ChunkStrategy = 'paragraph' | 'fixed' | 'semantic' | 'llm'

export interface ChunkingSettings {
  strategy: ChunkStrategy
  chunkSize: number
  chunkOverlap: number
}

export interface PipelineInstructions {
  qa: string
  extraction: string
  chunking: string
  tagging: string
  summary: string
}

// One chat model per generation step - null until the user picks one.
export interface GenerationModels {
  qa: string | null
  extraction: string | null
  chunking: string | null
  tagging: string | null
  summary: string | null
}

// Sliding-window params for steps that read several pages at once instead of
// one chunk at a time: summary (map-reduce), QA generation, entity/relation
// extraction, and semantic chunking.
export interface PipelineWindows {
  summaryPagesPerMap: number
  qaWindowPages: number
  qaSlidePages: number
  qaQuestionsPerWindow: number
  extractionWindowPages: number
  extractionSlidePages: number
  chunkingWindowPages: number
  chunkingSlidePages: number
  // Not a document-level window like the others above - how many QA pairs
  // are generated from the collection's description each time it changes.
  collectionQaCount: number
  // Longs documents (#372) : au-delà de samplingMinPages pages, le résumé, les questions et les entités ne lisent
  // pas tout le document (les chunks, si). Les valeurs par défaut lisent tout.
  samplingMinPages: number
  summaryMode: 'all' | 'percent' | 'pages'
  summaryPercent: number
  summaryHeadPercent: number | null
  summaryTailPercent: number | null
  summaryPageRanges: string
  qaMaxQuestions: number | null
  extractionPercent: number
  extractionMaxWindows: number | null
}

// Les appels au modèle que coûte l'indexation d'un document de `pages` pages (GET/POST .../indexing-estimate).
export interface IndexingEstimate {
  pages: number
  sampled: boolean
  chat: Record<string, number>
  embeddings: Record<string, number>
  collectionMax: number
}

export interface ChunkingSnapshot extends ChunkingSettings {
  embeddingModel: string
}

export interface EvaluationRun {
  id: string
  runAt: string
  k: number
  pairCount: number
  // The golden (test) pairs, scored apart - the numbers to follow over time.
  goldenPairCount: number
  validatedPairCount: number
  unvalidatedPairCount: number
  // The judge model (the collection's "evaluation" generation model).
  llmModel: string
  chunkingSnapshot: ChunkingSnapshot
  // Score averages over the reference (non-golden) / golden / every pair, keyed by metric
  // name - the keys are whatever the run's artifact actually scored, so a new metric flows
  // through with zero frontend model change (labels: utils/evaluationMetrics.ts).
  // Null when that subset is empty, when nothing was scored, or when the run
  // predates the promptfoo migration (no artifact); a metric a run predates simply
  // doesn't appear in its object.
  metrics: Record<string, number> | null
  goldenMetrics: Record<string, number> | null
  allMetrics: Record<string, number> | null
  // The share of golden (test) pairs that passed (every assertion at or above its
  // threshold), in [0, 1] - null when the run has no golden pair or no artifact.
  goldenPassRate: number | null
  // The same share over the reference (non-golden) pairs, and over every pair of the
  // run - each null when its subset is empty or the run has no artifact.
  referencePassRate: number | null
  overallPassRate: number | null
  // Whether the report/results.json artifacts exist (download links, report preview) -
  // false on the runs predating the promptfoo migration.
  hasArtifacts: boolean
}

export type CollectionVisibility = 'private' | 'public'

// One step of a collection's place in the sub-collection tree (#215).
export interface CollectionPathItem {
  id: string
  name: string
}

export type ShareSubjectType = 'user' | 'group'
export type ShareStatus = 'pending' | 'active'

export interface Share {
  id: string
  subjectType: ShareSubjectType
  status: ShareStatus
  // Non-reversible ("j***@e***.com") - never the full email/group the owner typed. See
  // backend/app/core/sharing.py.
  displayHint: string
  createdAt: string
  // Set when the share is on an ancestor and only applies here by inheritance (#216) - it can only
  // be revoked on that ancestor.
  inheritedFrom: CollectionPathItem | null
}

export interface Collection {
  id: string
  name: string
  description: string
  descriptionMeta: FieldStamp | null
  tags: string[]
  tagsMeta: FieldStamp | null
  updatedAt: string
  visibility: CollectionVisibility
  // Whether the current user owns this collection - false for a public collection browsed by
  // someone else, or one shared with them. Gates every write action in the UI.
  isOwner: boolean
  // Sub-collections (#215), all relative to what the current user can read: `parentId` is null
  // for a top-level collection or one whose parent they can't read, `path` runs from the root down
  // to the parent, `childrenCount` counts readable direct sub-collections.
  parentId: string | null
  path: CollectionPathItem[]
  childrenCount: number
  // Counted server-side, so a card shows them without the documents being loaded.
  documentCount: number
  indexedDocumentCount: number
  // Read access is inherited down the tree (#216): a private collection under a public one is
  // readable by everyone all the same - the nearest public ancestor, or null.
  inheritedPublicFrom: CollectionPathItem | null
  documents: CollectionDocument[]
  qaPairs: QaPair[]
  entities: Entity[]
  relations: Relation[]
  chunks: Chunk[]
  chunkingSettings: ChunkingSettings
  embeddingModel: string
  // The model of the vectors the active index holds, when it isn't embeddingModel yet (#12): the
  // chosen model only applies once the index has been rebuilt with it.
  indexEmbeddingModel: string | null
  reindexRequired: boolean
  instructions: PipelineInstructions
  generationModels: GenerationModels
  pipelineWindows: PipelineWindows
  evaluationRuns: EvaluationRun[]
  // Fetched on demand (owner-only endpoint), like qaPairs/entities - empty until
  // refreshShares/useCollections has run once for this collection.
  shares: Share[]
}
