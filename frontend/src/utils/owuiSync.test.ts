import assert from 'node:assert/strict'
import { test } from 'node:test'
import { accountRows, runStatus } from './owuiSync.ts'

test('a run that is going on is in progress, unless it never ended', () => {
  assert.deepEqual(runStatus({ status: 'running', stalled: false, withProblems: false }), { label: 'En cours', tone: 'info' })
  assert.deepEqual(runStatus({ status: 'running', stalled: true, withProblems: false }), { label: 'Interrompue', tone: 'error' })
})

test('a run that ended says whether it went well', () => {
  assert.equal(runStatus({ status: 'done', stalled: false, withProblems: false }).tone, 'success')
  assert.deepEqual(runStatus({ status: 'done', stalled: false, withProblems: true }), {
    label: 'Terminée avec des problèmes',
    tone: 'warning',
  })
})

test('a run that could not start failed', () => {
  assert.deepEqual(runStatus({ status: 'failed', stalled: false, withProblems: true }), { label: 'Échec', tone: 'error' })
})

test('the account is read group by group, knowledge base by knowledge base, file by file', () => {
  const counts = { seen: 2, errors: 0, dropped: 0 }

  assert.deepEqual(
    accountRows({ files: counts, groups: counts, knowledgeBases: counts }).map((row) => row.label),
    ['Groupes', 'Knowledge bases', 'Fichiers'],
  )
})

test('a kind the account does not have is left out, and no account has no row', () => {
  assert.deepEqual(accountRows({ files: { seen: 1, errors: 0, dropped: 0 } }).map((row) => row.label), ['Fichiers'])
  assert.deepEqual(accountRows(null), [])
})
