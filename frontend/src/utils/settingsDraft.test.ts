import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  assignDraft,
  changedSections,
  cloneDraft,
  commonModel,
  confirmations,
  draftFromCollection,
  setCommonModel,
  toPatch,
  validateSettings,
  type SettingsDraft,
} from './settingsDraft.ts'

const collection = {
  chunkingSettings: { strategy: 'llm', chunkSize: 512, chunkOverlap: 50 },
  embeddingModel: 'embedder',
  captionEngine: 'local',
  captionModel: null,
  instructions: { qa: 'q', extraction: 'e', chunking: 'c', tagging: 't', summary: 's' },
  generationModels: { qa: 'gpt', extraction: null, chunking: null, tagging: null, summary: 'gpt' },
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

test('un brouillon fraîchement lu n\'a aucune modification ni erreur', () => {
  assert.deepEqual(changedSections(fresh(), fresh()), [])
  assert.deepEqual(confirmations(fresh(), fresh()), [])
  assert.deepEqual(validateSettings(fresh()), {})
})

test('les sections modifiées sont nommées, chacune avec ses propres champs', () => {
  const draft = fresh()
  draft.instructions.qa = 'autre'
  draft.windows.extractionWindowPages = 6
  draft.longDocs.qaMaxQuestions = 100
  draft.models.tagging = 'gpt'
  assert.deepEqual(changedSections(draft, fresh()), ['qa', 'extraction', 'tagging', 'longDocs'])
})

test('découpage et embedding demandent confirmation, pas le reste', () => {
  const draft = fresh()
  draft.instructions.summary = 'autre'
  assert.deepEqual(confirmations(draft, fresh()), [])

  draft.chunking.strategy = 'paragraph'
  draft.embeddingModel = 'autre-embedder'
  assert.equal(confirmations(draft, fresh()).length, 2)
})

test('les champs numériques sont bornés comme avant, la taille des chunks seulement quand elle compte', () => {
  const draft = fresh()
  draft.windows.qaWindowPages = 0
  draft.windows.summaryPagesPerMap = 51
  draft.windows.collectionQaCount = ''
  draft.chunking.chunkSize = 10
  assert.deepEqual(Object.keys(validateSettings(draft)).sort(), ['collectionQaCount', 'qaWindowPages', 'summaryPagesPerMap'])

  draft.chunking.strategy = 'fixed'
  assert.equal('chunkSize' in validateSettings(draft), true)
  draft.chunking.chunkSize = 512
  draft.chunking.chunkOverlap = 600
  assert.equal('chunkOverlap' in validateSettings(draft), true)
})

test('les erreurs des longs documents sont aussi remontées', () => {
  const draft = fresh()
  draft.longDocs.summaryMode = 'percent'
  draft.longDocs.summaryPercent = 0
  assert.deepEqual(Object.keys(validateSettings(draft)), ['summaryPercent'])
})

test('la requête n\'envoie le modèle d\'embedding que s\'il a changé, et les modèles choisis seulement', () => {
  const draft = fresh()
  const unchanged = toPatch(draft, fresh())
  assert.equal('embedding_model' in unchanged, false)
  assert.deepEqual(unchanged.generation_models, { qa: 'gpt', summary: 'gpt' })
  assert.equal(unchanged.chunking_strategy, 'llm')
  assert.equal(unchanged.pipeline_windows.qa_window_pages, 2)
  assert.equal(unchanged.pipeline_windows.summary_mode, 'all')
  assert.equal(unchanged.pipeline_windows.qa_max_questions, null)

  draft.embeddingModel = 'autre'
  assert.equal(toPatch(draft, fresh()).embedding_model, 'autre')
})

test('un modèle commun à toutes les étapes se règle d\'un coup, et se reconnaît', () => {
  const draft = fresh()
  assert.equal(commonModel(draft.models), null)
  setCommonModel(draft.models, 'gpt')
  assert.equal(commonModel(draft.models), 'gpt')
  assert.deepEqual(Object.values(draft.models), ['gpt', 'gpt', 'gpt', 'gpt', 'gpt'])
})

test('assignDraft recopie sans partager d\'objets avec la source', () => {
  const source = fresh()
  const target = fresh()
  target.instructions.qa = 'x'
  assignDraft(target, source)
  source.instructions.qa = 'modifié après'
  assert.equal(target.instructions.qa, 'q')
  assert.deepEqual(cloneDraft(target), fresh())
})

test('le moteur de description suit le brouillon, et le modèle est vidé quand le moteur est local', () => {
  const draft = fresh()
  assert.deepEqual(draft.captions, { engine: 'local', model: '' })
  draft.captions = { engine: 'openai', model: 'gpt-4o' }
  const patch = toPatch(draft, fresh())
  assert.equal(patch.caption_engine, 'openai')
  assert.equal(patch.caption_model, 'gpt-4o')
  assert.ok(changedSections(draft, fresh()).includes('captions'))
  draft.captions.engine = 'local'
  assert.equal(toPatch(draft, fresh()).caption_model, '')
})
