import assert from 'node:assert/strict'
import { test } from 'node:test'
import { habitualFirst } from './habitualFirst.ts'

const rh = { id: 'rh' }
const it = { id: 'it' }
const achats = { id: 'achats' }

test('les collections habituelles passent devant, la plus consultée en tête, les autres gardent leur ordre', () => {
  assert.deepEqual(habitualFirst([achats, rh, it], ['it', 'rh']), [it, rh, achats])
  assert.deepEqual(habitualFirst([achats, it], ['it']), [it, achats])
})

test('sans habitude, rien ne change', () => {
  const items = [achats, rh]

  assert.equal(habitualFirst(items, []), items)
})

test('une habitude inconnue ne fait rien apparaître et rien disparaître', () => {
  assert.deepEqual(habitualFirst([achats, rh], ['fantome']), [achats, rh])
  assert.equal(habitualFirst([achats, rh, it], ['rh']).length, 3)
})
