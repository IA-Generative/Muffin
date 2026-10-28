import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isHiddenMetric, metricLabel, metricTooltip, orderedMetricKeys } from './evaluationMetrics.ts'

test('a known metric renders its French label', () => {
  assert.equal(metricLabel('factuality'), 'Factualité')
  assert.equal(metricLabel('context_faithfulness'), 'Fidélité au contexte')
})

test('an unknown metric falls back to its raw key - the backend serves metrics this registry never heard of', () => {
  assert.equal(metricLabel('answer_relevance'), 'answer_relevance')
  assert.equal(metricTooltip('answer_relevance'), undefined)
})

test('known metrics keep their registry order, unknown ones sort after them', () => {
  assert.deepEqual(
    orderedMetricKeys(['context_faithfulness', 'answer_relevance', 'factuality']),
    ['factuality', 'context_faithfulness', 'answer_relevance'],
  )
})

test('a subset of the known metrics keeps the relative registry order', () => {
  assert.deepEqual(orderedMetricKeys(['context_faithfulness']), ['context_faithfulness'])
  assert.deepEqual(orderedMetricKeys([]), [])
})

test('a hidden metric is never listed - the chunk count is a diagnostic, not a score to show', () => {
  assert.equal(isHiddenMetric('context_chunk_count'), true)
  assert.equal(isHiddenMetric('factuality'), false)
  assert.deepEqual(orderedMetricKeys(['context_chunk_count', 'factuality']), ['factuality'])
})
