import assert from 'node:assert/strict'
import { test } from 'node:test'
import { applyProfile, profileById } from './collectionProfiles.ts'
import { draftFromCollection, type SettingsDraft } from './settingsDraft.ts'
import { chunkingSummary, isEverythingRead, longDocsSummary, stepSummary, summaryReadingSummary } from './settingsSummary.ts'

const collection = {
  chunkingSettings: { strategy: 'llm', chunkSize: 512, chunkOverlap: 50 },
  embeddingModel: 'embedder',
  instructions: { qa: '', extraction: '', chunking: '', tagging: '', summary: '' },
  generationModels: { qa: 'gpt', extraction: null, chunking: null, tagging: null, summary: null },
  pipelineWindows: {
    summaryPagesPerMap: 5, qaWindowPages: 2, qaSlidePages: 1, qaQuestionsPerWindow: 3, extractionWindowPages: 4,
    extractionSlidePages: 1, chunkingWindowPages: 2, chunkingSlidePages: 1, collectionQaCount: 3,
    samplingMinPages: 100, summaryMode: 'all', summaryPercent: 30, summaryHeadPercent: null, summaryTailPercent: null,
    summaryPageRanges: '', qaMaxQuestions: null, extractionPercent: 100, extractionMaxWindows: null,
  },
} as unknown as Parameters<typeof draftFromCollection>[0]

const fresh = (): SettingsDraft => draftFromCollection(collection)

test('par défaut, tout est lu', () => {
  assert.equal(isEverythingRead(fresh()), true)
  assert.equal(longDocsSummary(fresh()), 'Tout est lu, quelle que soit la longueur du document')
})

test('ce qui n\'est lu qu\'en partie est dit, rien de plus', () => {
  const draft = fresh()
  applyProfile(draft, profileById('fast'))
  assert.equal(
    longDocsSummary(draft),
    'Au-delà de 100 pages : résumé : 30 % (moitié au début, moitié à la fin) · 100 questions au plus · entités : 20 % des pages',
  )

  const capped = fresh()
  capped.longDocs.extractionMaxWindows = 50
  assert.equal(longDocsSummary(capped), 'Au-delà de 100 pages : entités : 100 % des pages, 50 fenêtres au plus')
})

test('le résumé dit le début et la fin séparés, ou les pages choisies', () => {
  const draft = fresh()
  draft.longDocs.summaryMode = 'percent'
  draft.longDocs.separateEnds = true
  draft.longDocs.summaryHeadPercent = 20
  draft.longDocs.summaryTailPercent = 10
  assert.equal(summaryReadingSummary(draft), 'début 20 % et fin 10 %')
  draft.longDocs.summaryMode = 'pages'
  draft.longDocs.summaryPageRanges = ' 1-5, 40- '
  assert.equal(summaryReadingSummary(draft), 'pages 1-5, 40-')
})

test('le découpage et les étapes se disent en une ligne', () => {
  const draft = fresh()
  assert.match(chunkingSummary(draft), /^Par le modèle/)
  draft.chunking.strategy = 'fixed'
  assert.equal(chunkingSummary(draft), 'Par blocs de taille fixe (512 tokens)')
  assert.equal(stepSummary(draft, 'qa'), 'gpt')
  assert.equal(stepSummary(draft, 'summary'), 'modèle par défaut')
  draft.instructions.summary = 'Court.'
  assert.equal(stepSummary(draft, 'summary'), 'modèle par défaut · consignes personnalisées')
})
