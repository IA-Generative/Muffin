import assert from 'node:assert/strict'
import { test } from 'node:test'
import { filterLocally, lexicalScore, needsServerSearch, searchableText } from './assistantSearch.ts'

const rh = { name: 'RH – congés', description: 'Répond sur les congés payés', suggestions: ['Combien de jours ?'] }
const achats = { name: 'Achats', description: 'Marchés publics', suggestions: [] }

test('la recherche locale ignore les accents, la casse et le pluriel', () => {
  assert.deepEqual(filterLocally([achats, rh], 'CONGE'), [rh])
  assert.deepEqual(filterLocally([achats, rh], 'marche'), [achats])
})

test('une question sans aucun mot en commun ne trouve rien', () => {
  assert.deepEqual(filterLocally([achats, rh], 'budget'), [])
})

test('les questions suggérées sont cherchées, et le meilleur score passe devant', () => {
  const both = { name: 'Congés', description: 'Congés payés', suggestions: [] }
  assert.deepEqual(filterLocally([rh, both], 'jours conges'), [rh, both])
  assert.equal(lexicalScore('conges payes', both), 1)
})

test('ce qui est cherché ne contient jamais les consignes ni les collections', () => {
  const secret = { ...rh, instructions: 'MOT-SECRET', collections: [{ id: 'c', name: 'Accords confidentiels' }] }
  assert.ok(!searchableText(secret).includes('SECRET') && !searchableText(secret).includes('confidentiels'))
  assert.deepEqual(filterLocally([secret], 'confidentiels'), [])
})

test('le serveur n’est interrogé que pour une vraie recherche parmi beaucoup d’assistants', () => {
  assert.equal(needsServerSearch('c', 50), false)
  assert.equal(needsServerSearch('congés', 7), false)
  assert.equal(needsServerSearch('congés', 8), true)
})
