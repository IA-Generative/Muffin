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

export interface Collection {
  id: string
  name: string
  description: string
  descriptionMeta: FieldStamp | null
  tags: string[]
  tagsMeta: FieldStamp | null
  updatedAt: string
  documents: CollectionDocument[]
  qaPairs: QaPair[]
  entities: Entity[]
  relations: Relation[]
  chunks: Chunk[]
  chunkingSettings: ChunkingSettings
  embeddingModel: string
  reindexRequired: boolean
  instructions: PipelineInstructions
  evaluationRuns: EvaluationRun[]
}
