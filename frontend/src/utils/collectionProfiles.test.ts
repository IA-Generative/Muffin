import assert from 'node:assert/strict'
import { test } from 'node:test'
import { applyProfile, detectProfile, PROFILES, profileById } from './collectionProfiles.ts'
import { draftFromCollection, validateSettings, type SettingsDraft } from './settingsDraft.ts'

const collection = {
  chunkingSettings: { strategy: 'llm', chunkSize: 512, chunkOverlap: 50 },
  embeddingModel: 'embedder',
  instructions: { qa: '', extraction: '', chunking: '', tagging: '', summary: '' },
  generationModels: { qa: null, extraction: null, chunking: null, tagging: null, summary: null },
  pipelineWindows: {
    summaryPagesPerMap: 5,
    qaWindowPages: 2,
    qaSlidePages: 1,
    qaQuestionsPerWindow: 3,
    extractionWindowPages: 4,
    extractionSlidePages: 1,
    chunkingWindowPages: 2,
    chunkingSlidePages: 1,
    collectionQaCount: 3,
    samplingMinPages: 100,
    summaryMode: 'all',
    summaryPercent: 30,
    summaryHeadPercent: null,
    summaryTailPercent: null,
    summaryPageRanges: '',
    qaMaxQuestions: null,
    extractionPercent: 100,
    extractionMaxWindows: null,
  },
} as unknown as Parameters<typeof draftFromCollection>[0]

const fresh = (): SettingsDraft => draftFromCollection(collection)

test('les réglages par défaut d\'une collection sont le profil précis', () => {
  assert.equal(detectProfile(fresh()), 'precise')
})

test('chaque profil, une fois appliqué, est reconnu et donne des réglages valides', () => {
  for (const profile of PROFILES) {
    const draft = fresh()
    applyProfile(draft, profile)
    assert.equal(detectProfile(draft), profile.id, profile.id)
    assert.deepEqual(validateSettings(draft), {}, profile.id)
  }
})

test('un profil règle le découpage et les longs documents, rien d\'autre', () => {
  const draft = fresh()
  draft.instructions.qa = 'Questions courtes.'
  draft.models.qa = 'gpt'
  draft.chunking.chunkSize = 800
  draft.longDocs.samplingMinPages = 250

  applyProfile(draft, profileById('fast'))

  assert.equal(draft.chunking.strategy, 'paragraph')
  assert.equal(draft.longDocs.summaryMode, 'percent')
  assert.equal(draft.longDocs.qaMaxQuestions, 100)
  assert.equal(draft.longDocs.extractionPercent, 20)
  assert.deepEqual(
    [draft.instructions.qa, draft.models.qa, draft.chunking.chunkSize, draft.longDocs.samplingMinPages],
    ['Questions courtes.', 'gpt', 800, 250],
  )
})

test('passer à « précis » après « rapide » retire tout ce que « rapide » avait plafonné', () => {
  const draft = fresh()
  applyProfile(draft, profileById('fast'))
  applyProfile(draft, profileById('precise'))
  assert.equal(draft.longDocs.summaryMode, 'all')
  assert.equal(draft.longDocs.qaMaxQuestions, '')
  assert.equal(draft.longDocs.extractionPercent, 100)
})

test('un réglage modifié à la main n\'est plus un profil : « personnalisé »', () => {
  const draft = fresh()
  applyProfile(draft, profileById('balanced'))
  draft.longDocs.qaMaxQuestions = 120
  assert.equal(detectProfile(draft), null)

  const separate = fresh()
  applyProfile(separate, profileById('balanced'))
  separate.longDocs.separateEnds = true
  assert.equal(detectProfile(separate), null)
})

test('un seul profil est recommandé', () => {
  assert.deepEqual(
    PROFILES.filter((profile) => profile.recommended).map((profile) => profile.id),
    ['balanced'],
  )
})
