import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isSearchable, normalizeQuery, snippetParts } from './conversationSearch.ts'

test('a query is trimmed and its spaces folded', () => {
  assert.equal(normalizeQuery('  télétravail   deux  jours '), 'télétravail deux jours')
})

test('a query shorter than two characters is not sent', () => {
  assert.equal(isSearchable(''), false)
  assert.equal(isSearchable('  a '), false)
  assert.equal(isSearchable('ab'), true)
})

test('the words found are flagged and the rest is plain text', () => {
  assert.deepEqual(snippetParts('Le \u0002télétravail\u0003 est autorisé'), [
    { text: 'Le ', match: false },
    { text: 'télétravail', match: true },
    { text: ' est autorisé', match: false },
  ])
})

test('two words found next to each other stay two pieces', () => {
  assert.deepEqual(snippetParts('\u0002plan\u0003 \u0002continuité\u0003'), [
    { text: 'plan', match: true },
    { text: ' ', match: false },
    { text: 'continuité', match: true },
  ])
})

test('the markup of a message is text, never markup', () => {
  assert.deepEqual(snippetParts('<script>alert(1)</script> \u0002télétravail\u0003'), [
    { text: '<script>alert(1)</script> ', match: false },
    { text: 'télétravail', match: true },
  ])
})

test('the citation markers and the line breaks are left out of a snippet', () => {
  assert.deepEqual(snippetParts('Deux jours \u0002par\u0003 semaine [a1b2c3].\nFin'), [
    { text: 'Deux jours ', match: false },
    { text: 'par', match: true },
    { text: ' semaine. Fin', match: false },
  ])
})

test('a snippet without any word flagged is one plain piece', () => {
  assert.deepEqual(snippetParts('Rien de marqué'), [{ text: 'Rien de marqué', match: false }])
  assert.deepEqual(snippetParts(''), [])
})
