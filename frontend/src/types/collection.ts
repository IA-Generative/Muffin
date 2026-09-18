export interface CollectionDocument {
  id: string
  name: string
  type: 'file' | 'url'
  status: 'pending' | 'indexing' | 'indexed' | 'error'
  progress: number
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
  origin: 'generated' | 'manual'
  validated: boolean
}

export type EntityType = 'personne' | 'organisation' | 'lieu' | 'date' | 'autre'

export interface Entity {
  id: string
  name: string
  type: EntityType
  mentions: number
}

export interface Relation {
  id: string
  from: string
  to: string
  type: string
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
}

export interface EvaluationMetrics {
  precisionAtK: number
  recallAtK: number
  mrr: number
  ndcg: number
}

export interface EvaluationResult {
  qaPairId: string
  question: string
  expectedAnswer: string
  generatedAnswer: string
  retrievedSources: string[]
  precisionAtK: number
  recallAtK: number
  reciprocalRank: number
  ndcg: number
}

export interface ChunkingSnapshot extends ChunkingSettings {
  embeddingModel: string
}

export interface EvaluationRun {
  id: string
  runAt: string
  k: number
  pairCount: number
  llmModel: string
  chunkingSnapshot: ChunkingSnapshot
  metrics: EvaluationMetrics
  results: EvaluationResult[]
}

export type CollectionVisibility = 'private' | 'public'

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
  documents: CollectionDocument[]
  qaPairs: QaPair[]
  entities: Entity[]
  relations: Relation[]
  chunks: Chunk[]
  chunkingSettings: ChunkingSettings
  embeddingModel: string
  reindexRequired: boolean
  instructions: PipelineInstructions
  generationModels: GenerationModels
  pipelineWindows: PipelineWindows
  evaluationRuns: EvaluationRun[]
  // Fetched on demand (owner-only endpoint), like qaPairs/entities - empty until
  // refreshShares/useCollections has run once for this collection.
  shares: Share[]
}
