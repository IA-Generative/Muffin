import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  cleanConfig,
  describeChanges,
  emptyDraft,
  outcomeLabel,
  splitList,
  totalsByGuardrail,
  tryPattern,
  verdictLabel,
} from './guardrails.ts'

test('une liste saisie en lignes ou séparée par des virgules perd ses vides et ses doublons', () => {
  assert.deepEqual(splitList('rh, compta\n  rh ,\n\n direction'), ['rh', 'compta', 'direction'])
  assert.deepEqual(splitList('  '), [])
})

test('la configuration envoyée ne garde pas ce qui est laissé vide', () => {
  const rules = cleanConfig('rules', {
    builtins: ['iban'],
    patterns: [
      { name: 'dossier', regex: 'DOS-\\d+' },
      { name: 'vide', regex: '  ' },
    ],
    terms: [' secret ', ''],
    max_chars: null,
    category: ' ',
  })
  assert.deepEqual(rules, {
    builtins: ['iban'],
    patterns: [{ name: 'dossier', regex: 'DOS-\\d+' }],
    terms: ['secret'],
    max_chars: null,
  })
  assert.deepEqual(cleanConfig('llm', { prompt: ' ', categories: ['injection'], threshold: 0.7, model: '' }), {
    categories: ['injection'],
    threshold: 0.7,
  })
  assert.deepEqual(cleanConfig('http', { url: ' https://moderation.example.test/check ' }), {
    url: 'https://moderation.example.test/check',
  })
})

test('un motif est essayé sur un texte, et un motif invalide est dit invalide', () => {
  assert.deepEqual(tryPattern('DOS-\\d{6}', 'voir DOS-123456 et DOS-654321'), { valid: true, matches: 2 })
  assert.deepEqual(tryPattern('(', 'texte'), { valid: false, matches: 0 })
  assert.deepEqual(tryPattern('', 'texte'), { valid: true, matches: 0 })
})

test('un garde-fou neuf est éteint, observe seulement, et un juge passe après les règles', () => {
  const rules = emptyDraft('rules')
  const llm = emptyDraft('llm')
  assert.deepEqual([rules.enabled, rules.enforcement, rules.onError, rules.stage], [false, 'monitor', 'fail_open', 1])
  assert.equal(llm.stage, 2)
  assert.equal(emptyDraft('http').config.url, '')
})

test('les lignes par jour sont additionnées par garde-fou, avec le temps moyen pesé par le nombre de verdicts', () => {
  const row = (name: string, evaluated: number, blocked: number, avg: number) => ({
    guardrailId: null,
    name,
    day: '2026-11-01',
    evaluated,
    flagged: blocked,
    blocked,
    failed: 0,
    avgLatencyMs: avg,
    maxLatencyMs: avg,
  })
  const totals = totalsByGuardrail([row('IBAN', 10, 2, 10), row('IBAN', 30, 1, 50), row('Juge', 5, 0, 400)])

  assert.deepEqual(
    totals.map((item) => [item.name, item.evaluated, item.blocked, item.avgLatencyMs]),
    [
      ['IBAN', 40, 3, 40],
      ['Juge', 5, 0, 400],
    ],
  )
  assert.equal(totals[0].blockRate, 3 / 40)
})

test('le journal dit ce qui a changé, et la version seule n’est pas un changement', () => {
  const entry = (action: string, before: Record<string, unknown> | null, after: Record<string, unknown> | null) => ({
    id: '1',
    guardrailName: 'IBAN',
    action,
    userDisplay: 'Root',
    before,
    after,
    createdAt: '2026-11-01T10:00:00Z',
  })

  assert.deepEqual(
    describeChanges(entry('updated', { enforcement: 'monitor', version: 1 }, { enforcement: 'block', version: 2 })),
    ['mode : monitor → block'],
  )
  assert.deepEqual(describeChanges(entry('updated', { enabled: false }, { enabled: true })), ['activé : non → oui'])
  assert.deepEqual(describeChanges(entry('updated', { config: { a: 1 } }, { config: { a: 2 } })), ['réglages modifiés'])
  assert.deepEqual(describeChanges(entry('created', null, {})), ['créé'])
  assert.deepEqual(describeChanges(entry('deleted', {}, null)), ['supprimé'])
})

test('les verdicts et les issues se disent en français', () => {
  assert.equal(verdictLabel('flagged'), 'Signalé')
  assert.equal(verdictLabel('autre'), 'autre')
  assert.equal(outcomeLabel('block'), 'La demande est bloquée')
})
