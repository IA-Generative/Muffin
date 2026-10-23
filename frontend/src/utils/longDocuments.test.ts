import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  draftFromSettings,
  formatPages,
  joinPercent,
  parsePageRanges,
  setSeparateEnds,
  splitPercent,
  toPayload,
  validateLongDocuments,
  type LongDocumentsDraft,
  type LongDocumentsSettings,
} from './longDocuments.ts'

const defaults: LongDocumentsSettings = {
  samplingMinPages: 100,
  summaryMode: 'all',
  summaryPercent: 30,
  summaryHeadPercent: null,
  summaryTailPercent: null,
  summaryPageRanges: '',
  qaMaxQuestions: null,
  extractionPercent: 100,
  extractionMaxWindows: null,
}

const draft = (changes: Partial<LongDocumentsDraft> = {}): LongDocumentsDraft => ({
  ...draftFromSettings(defaults),
  ...changes,
})

test('les plages de pages : une page, une plage, une plage ouverte', () => {
  assert.deepEqual(parsePageRanges('1-5, 40-45, 90-'), {
    ok: true,
    ranges: [
      { first: 1, last: 5 },
      { first: 40, last: 45 },
      { first: 90, last: null },
    ],
  })
  assert.deepEqual(parsePageRanges(' 7 ,  12 - 14 '), {
    ok: true,
    ranges: [
      { first: 7, last: 7 },
      { first: 12, last: 14 },
    ],
  })
  assert.deepEqual(parsePageRanges(''), { ok: true, ranges: [] })
})

test('les plages mal formées sont refusées, avec la partie fautive', () => {
  for (const text of ['trois à cinq', '5-2', '0-3', '1-5, x', '1--5', '-5']) {
    const result = parsePageRanges(text)
    assert.equal(result.ok, false, text)
  }
  const result = parsePageRanges('1-5, x')
  assert.equal(result.ok === false && result.error.includes('« x »'), true)
})

test('par défaut rien ne change: tout le document, pas de plafond, et aucune erreur', () => {
  assert.deepEqual(validateLongDocuments(draft()), {})
  const payload = toPayload(draft())
  assert.equal(payload.summary_mode, 'all')
  assert.equal(payload.qa_max_questions, null)
  assert.equal(payload.extraction_percent, 100)
  assert.equal(payload.extraction_max_windows, null)
  assert.equal(payload.summary_head_percent, null)
})

test('les pourcentages hors de 1-100 sont signalés à côté du bon champ', () => {
  const errors = validateLongDocuments(
    draft({ summaryMode: 'percent', summaryPercent: 0, extractionPercent: 101, samplingMinPages: 0 }),
  )
  assert.deepEqual(Object.keys(errors).sort(), ['extractionPercent', 'samplingMinPages', 'summaryPercent'])
  assert.deepEqual(validateLongDocuments(draft({ summaryMode: 'percent', summaryPercent: 100 })), {})
})

test('un pourcentage de résumé n\'est vérifié que lorsque le mode « partie » est choisi', () => {
  assert.deepEqual(validateLongDocuments(draft({ summaryMode: 'all', summaryPercent: 0 })), {})
})

test('un champ de plafond vidé veut dire sans plafond, un plafond invalide est refusé', () => {
  assert.deepEqual(validateLongDocuments(draft({ qaMaxQuestions: '', extractionMaxWindows: '' })), {})
  const errors = validateLongDocuments(draft({ qaMaxQuestions: 0, extractionMaxWindows: 2.5 }))
  assert.deepEqual(Object.keys(errors).sort(), ['extractionMaxWindows', 'qaMaxQuestions'])
})

test('début + fin supérieurs à 100 % ou nuls sont refusés', () => {
  const separate = { summaryMode: 'percent', separateEnds: true } as const
  assert.deepEqual(Object.keys(validateLongDocuments(draft({ ...separate, summaryHeadPercent: 60, summaryTailPercent: 60 }))), [
    'summaryTailPercent',
  ])
  assert.deepEqual(Object.keys(validateLongDocuments(draft({ ...separate, summaryHeadPercent: 0, summaryTailPercent: 0 }))), [
    'summaryTailPercent',
  ])
  assert.deepEqual(validateLongDocuments(draft({ ...separate, summaryHeadPercent: 0, summaryTailPercent: 25 })), {})
  assert.deepEqual(validateLongDocuments(draft({ ...separate, summaryHeadPercent: 70, summaryTailPercent: 30 })), {})
})

test('le mode « pages précises » veut au moins une plage valide', () => {
  assert.deepEqual(Object.keys(validateLongDocuments(draft({ summaryMode: 'pages' }))), ['summaryPageRanges'])
  assert.deepEqual(Object.keys(validateLongDocuments(draft({ summaryMode: 'pages', summaryPageRanges: '5-2' }))), [
    'summaryPageRanges',
  ])
  assert.deepEqual(validateLongDocuments(draft({ summaryMode: 'pages', summaryPageRanges: '1-5, 40-45' })), {})
  // une saisie mal formée est refusée même si le mode n'est plus « pages » : le backend la refuserait aussi
  assert.deepEqual(Object.keys(validateLongDocuments(draft({ summaryPageRanges: 'abc' }))), ['summaryPageRanges'])
})

test('le pourcentage symétrique se répartit moitié au début, moitié à la fin', () => {
  assert.deepEqual(splitPercent(30), [15, 15])
  assert.deepEqual(splitPercent(25), [13, 12])
  assert.deepEqual(splitPercent(1), [1, 0])
  assert.equal(joinPercent(15, 15), 30)
  assert.equal(joinPercent(70, 70), 100)
  assert.equal(joinPercent(0, 0), 1)
})

test('basculer en début/fin séparés garde ce qui était réglé, et le retour aussi', () => {
  const state = draft({ summaryMode: 'percent', summaryPercent: 30 })

  setSeparateEnds(state, true)
  assert.deepEqual([state.separateEnds, state.summaryHeadPercent, state.summaryTailPercent], [true, 15, 15])
  assert.deepEqual(toPayload(state).summary_head_percent, 15)

  state.summaryHeadPercent = 40
  setSeparateEnds(state, false)
  assert.deepEqual([state.separateEnds, state.summaryPercent], [false, 55])
  const payload = toPayload(state)
  assert.equal(payload.summary_head_percent, null)
  assert.equal(payload.summary_tail_percent, null)
})

test('le début et la fin séparés ne sont envoyés que pour le mode « partie »', () => {
  const state = draft({ summaryMode: 'pages', separateEnds: true, summaryHeadPercent: 10, summaryTailPercent: 10 })
  assert.equal(toPayload(state).summary_head_percent, null)
})

test('une collection qui avait un début et une fin séparés les retrouve', () => {
  const state = draftFromSettings({
    ...defaults,
    summaryMode: 'percent',
    summaryHeadPercent: 20,
    summaryTailPercent: 10,
  })
  assert.deepEqual([state.separateEnds, state.summaryHeadPercent, state.summaryTailPercent], [true, 20, 10])
})

test('les pages couvertes par un résumé partiel se lisent', () => {
  assert.equal(formatPages([[1, 30], [100, 100], [271, 300]]), '1-30, 100, 271-300')
})
