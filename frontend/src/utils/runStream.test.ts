import assert from 'node:assert/strict'
import { test } from 'node:test'
import { applyDelta, isEndingStatus } from './runStream.ts'

test('the pieces of an answer are put end to end', () => {
  let shown = ''
  for (const text of ['Le télé', 'travail', ' est autorisé']) shown = applyDelta(shown, { text })
  assert.equal(shown, 'Le télétravail est autorisé')
})

test('a piece that replaces what is shown takes its place', () => {
  assert.equal(applyDelta('```', { text: 'Bonjour', replace: true }), 'Bonjour')
  assert.equal(applyDelta('Bon', { text: 'jour', replace: false }), 'Bonjour')
})

test('a run is over, or waits for the user, when its stream has nothing more to say', () => {
  for (const status of ['completed', 'failed', 'cancelled', 'waiting_for_user']) assert.equal(isEndingStatus(status), true)
  for (const status of ['queued', 'running', 'replanning']) assert.equal(isEndingStatus(status), false)
})
