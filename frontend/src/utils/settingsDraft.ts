// Le brouillon des réglages d'une collection : tout ce que l'onglet Paramètres modifie, enregistré d'un seul bloc.
// Pur (pas de Vue, pas de réseau) pour que la validation, le calcul des modifications et le corps de la requête
// soient testables.
import type { ChunkingSettings, Collection, GenerationModels, PipelineInstructions } from '../types/collection.ts'
import {
  draftFromSettings,
  toPayload,
  validateLongDocuments,
  type LongDocumentsDraft,
  type LongDocumentsErrors,
  type NumberField,
} from './longDocuments.ts'

export type StepKey = 'qa' | 'extraction' | 'chunking' | 'tagging' | 'summary'
export const STEP_KEYS: StepKey[] = ['summary', 'qa', 'extraction', 'tagging', 'chunking']

// '' : pas de modèle choisi, le serveur prend le premier disponible.
export type StepModels = Record<StepKey, string>

export const WINDOW_KEYS = {
  summaryPagesPerMap: 'summary_pages_per_map',
  qaWindowPages: 'qa_window_pages',
  qaSlidePages: 'qa_slide_pages',
  qaQuestionsPerWindow: 'qa_questions_per_window',
  extractionWindowPages: 'extraction_window_pages',
  extractionSlidePages: 'extraction_slide_pages',
  chunkingWindowPages: 'chunking_window_pages',
  chunkingSlidePages: 'chunking_slide_pages',
  collectionQaCount: 'collection_qa_count',
} as const
export type WindowKey = keyof typeof WINDOW_KEYS
export type WindowFields = Record<WindowKey, NumberField>

export interface SettingsDraft {
  chunking: { strategy: ChunkingSettings['strategy']; chunkSize: NumberField; chunkOverlap: NumberField }
  embeddingModel: string
  instructions: PipelineInstructions
  models: StepModels
  windows: WindowFields
  longDocs: LongDocumentsDraft
}

export type SettingsSection = 'embedding' | 'chunking' | 'summary' | 'qa' | 'extraction' | 'tagging' | 'longDocs'

export const SECTION_LABELS: Record<SettingsSection, string> = {
  embedding: "Modèle d'embedding",
  chunking: 'Découpage',
  summary: 'Résumé',
  qa: 'Questions-réponses',
  extraction: 'Entités et relations',
  tagging: 'Tags',
  longDocs: 'Longs documents',
}

type CollectionSettingsSource = Pick<
  Collection,
  'chunkingSettings' | 'embeddingModel' | 'instructions' | 'generationModels' | 'pipelineWindows'
>

export function draftFromCollection(collection: CollectionSettingsSource): SettingsDraft {
  const windows = collection.pipelineWindows
  const models = collection.generationModels
  return {
    chunking: {
      strategy: collection.chunkingSettings.strategy,
      chunkSize: collection.chunkingSettings.chunkSize,
      chunkOverlap: collection.chunkingSettings.chunkOverlap,
    },
    embeddingModel: collection.embeddingModel,
    instructions: { ...collection.instructions },
    models: {
      qa: models.qa ?? '',
      extraction: models.extraction ?? '',
      chunking: models.chunking ?? '',
      tagging: models.tagging ?? '',
      summary: models.summary ?? '',
    },
    windows: {
      summaryPagesPerMap: windows.summaryPagesPerMap,
      qaWindowPages: windows.qaWindowPages,
      qaSlidePages: windows.qaSlidePages,
      qaQuestionsPerWindow: windows.qaQuestionsPerWindow,
      extractionWindowPages: windows.extractionWindowPages,
      extractionSlidePages: windows.extractionSlidePages,
      chunkingWindowPages: windows.chunkingWindowPages,
      chunkingSlidePages: windows.chunkingSlidePages,
      collectionQaCount: windows.collectionQaCount,
    },
    longDocs: draftFromSettings(windows),
  }
}

export function cloneDraft(draft: SettingsDraft): SettingsDraft {
  return JSON.parse(JSON.stringify(draft)) as SettingsDraft
}

// Remplace le contenu d'un brouillon réactif sans changer son identité.
export function assignDraft(target: SettingsDraft, source: SettingsDraft): void {
  const copy = cloneDraft(source)
  target.chunking = copy.chunking
  target.embeddingModel = copy.embeddingModel
  target.instructions = copy.instructions
  target.models = copy.models
  target.windows = copy.windows
  target.longDocs = copy.longDocs
}

// -- ce qui a changé ---------------------------------------------------------------------------------------------

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

const pick = <T extends object, K extends keyof T>(source: T, keys: K[]) =>
  Object.fromEntries(keys.map((key) => [key, source[key]]))

export function changedSections(draft: SettingsDraft, saved: SettingsDraft): SettingsSection[] {
  const changed: SettingsSection[] = []
  const check = (section: SettingsSection, now: unknown, before: unknown) => {
    if (!same(now, before)) changed.push(section)
  }
  const part = (d: SettingsDraft) => ({
    embedding: d.embeddingModel,
    chunking: [
      d.chunking,
      d.instructions.chunking,
      d.models.chunking,
      pick(d.windows, ['chunkingWindowPages', 'chunkingSlidePages']),
    ],
    summary: [d.instructions.summary, d.models.summary, d.windows.summaryPagesPerMap],
    qa: [
      d.instructions.qa,
      d.models.qa,
      pick(d.windows, ['qaWindowPages', 'qaSlidePages', 'qaQuestionsPerWindow', 'collectionQaCount']),
    ],
    extraction: [
      d.instructions.extraction,
      d.models.extraction,
      pick(d.windows, ['extractionWindowPages', 'extractionSlidePages']),
    ],
    tagging: [d.instructions.tagging, d.models.tagging],
    longDocs: d.longDocs,
  })
  const now = part(draft)
  const before = part(saved)
  for (const section of Object.keys(SECTION_LABELS) as SettingsSection[]) check(section, now[section], before[section])
  return changed
}

// Ce qui change la façon dont les documents déjà indexés sont lus : à confirmer avant d'enregistrer.
export function confirmations(draft: SettingsDraft, saved: SettingsDraft): string[] {
  const messages: string[] = []
  if (!same(draft.chunking, saved.chunking)) {
    messages.push('Le découpage a changé : les documents déjà indexés devront peut-être être réindexés.')
  }
  if (draft.embeddingModel !== saved.embeddingModel) {
    messages.push("Le modèle d'embedding a changé : les documents déjà indexés devront être réindexés.")
  }
  return messages
}

// -- validation --------------------------------------------------------------------------------------------------

export type SettingsErrors = LongDocumentsErrors & Partial<Record<WindowKey | 'chunkSize' | 'chunkOverlap', string>>

const WINDOW_LIMITS: Record<WindowKey, { min: number; max: number; label: string }> = {
  summaryPagesPerMap: { min: 1, max: 50, label: 'Pages par lot' },
  qaWindowPages: { min: 1, max: 20, label: 'Pages lues à la fois' },
  qaSlidePages: { min: 1, max: 20, label: 'Avancée entre deux lectures' },
  qaQuestionsPerWindow: { min: 1, max: 20, label: 'Questions par lecture' },
  extractionWindowPages: { min: 1, max: 20, label: 'Pages lues à la fois' },
  extractionSlidePages: { min: 1, max: 20, label: 'Avancée entre deux lectures' },
  chunkingWindowPages: { min: 1, max: 20, label: 'Pages lues à la fois' },
  chunkingSlidePages: { min: 1, max: 20, label: 'Avancée entre deux lectures' },
  collectionQaCount: { min: 1, max: 20, label: 'Questions sur la description' },
}

function boundedInteger(value: NumberField, min: number, max: number, label: string): string | undefined {
  if (value === '' || !Number.isInteger(value)) return `${label} : saisir un nombre entier.`
  if (value < min || value > max) return `${label} : entre ${min} et ${max}.`
  return undefined
}

export function validateSettings(draft: SettingsDraft): SettingsErrors {
  const errors: SettingsErrors = { ...validateLongDocuments(draft.longDocs) }
  if (draft.chunking.strategy === 'paragraph' || draft.chunking.strategy === 'fixed') {
    const size = boundedInteger(draft.chunking.chunkSize, 64, 4096, 'Taille des chunks')
    if (size) errors.chunkSize = size
    const overlap = boundedInteger(draft.chunking.chunkOverlap, 0, 512, 'Chevauchement')
    if (overlap) errors.chunkOverlap = overlap
  }
  for (const key of Object.keys(WINDOW_KEYS) as WindowKey[]) {
    const { min, max, label } = WINDOW_LIMITS[key]
    const message = boundedInteger(draft.windows[key], min, max, label)
    if (message) errors[key] = message
  }
  return errors
}

// -- la requête --------------------------------------------------------------------------------------------------

export interface SettingsPatch {
  chunking_strategy: string
  chunk_size: number
  chunk_overlap: number
  embedding_model?: string
  instructions: PipelineInstructions
  generation_models: Partial<GenerationModels>
  pipeline_windows: Record<string, number | string | null>
}

// Valable seulement quand le brouillon est valide (voir validateSettings).
export function toPatch(draft: SettingsDraft, saved: SettingsDraft): SettingsPatch {
  const windows: Record<string, number> = {}
  for (const key of Object.keys(WINDOW_KEYS) as WindowKey[]) windows[WINDOW_KEYS[key]] = draft.windows[key] as number
  const models: Partial<GenerationModels> = {}
  for (const step of STEP_KEYS) if (draft.models[step]) models[step] = draft.models[step]
  return {
    chunking_strategy: draft.chunking.strategy,
    chunk_size: draft.chunking.chunkSize as number,
    chunk_overlap: draft.chunking.chunkOverlap as number,
    ...(draft.embeddingModel !== saved.embeddingModel ? { embedding_model: draft.embeddingModel } : {}),
    instructions: { ...draft.instructions },
    generation_models: models,
    pipeline_windows: { ...windows, ...toPayload(draft.longDocs) },
  }
}

// Un seul modèle pour toutes les étapes de génération : le choix « simple » ; null quand ils diffèrent.
export function commonModel(models: StepModels): string | null {
  const values = new Set(STEP_KEYS.map((step) => models[step]))
  return values.size === 1 ? [...values][0] : null
}

export function setCommonModel(models: StepModels, model: string): void {
  for (const step of STEP_KEYS) models[step] = model
}
