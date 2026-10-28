import assert from 'node:assert/strict'
import { test } from 'node:test'
import { answerHasNoSource } from './answerSources.ts'

test('an answer built on excerpts that cites none of them has no source', () => {
  assert.equal(answerHasNoSource([{ evidence_id: 'a' }, { evidence_id: 'b' }], undefined), true)
  assert.equal(answerHasNoSource([{ evidence_id: 'a' }], []), true)
})

test('an answer that shows a source has one', () => {
  assert.equal(answerHasNoSource([{ evidence_id: 'a' }], [{ title: '1. politique.pdf' }]), false)
})

test('an answer that consulted nothing says so itself and gets no notice', () => {
  assert.equal(answerHasNoSource([], undefined), false)
  assert.equal(answerHasNoSource(null, undefined), false)
  assert.equal(answerHasNoSource(undefined, undefined), false)
})
