import assert from 'node:assert/strict'
import { test } from 'node:test'
import { filterLocally, lexicalScore, needsServerSearch, searchableText } from './toolSearch.ts'

const convertir = {
  name: 'convertir_devise',
  description: 'Convertit un montant d’une devise dans une autre',
  inputSchema: { properties: { montant: { default: 'VALEUR-SECRETE' }, cible: {} } },
}
const agenda = { name: 'agenda', description: 'Lit le calendrier des réunions', inputSchema: {} }

test('la recherche locale cherche dans la description, ignore accents, casse et pluriel', () => {
  assert.deepEqual(filterLocally([agenda, convertir], 'DEVISES'), [convertir])
  assert.deepEqual(filterLocally([agenda, convertir], 'reunion'), [agenda])
})

test('le nom d’un outil est cherché mot par mot, et le nom d’un paramètre aussi', () => {
  assert.equal(lexicalScore('convertir', convertir), 1)
  assert.equal(lexicalScore('montant', convertir), 1)
})

test('les mots trop courants ne font rien trouver', () => {
  assert.deepEqual(filterLocally([agenda, convertir], 'des'), [])
  assert.deepEqual(filterLocally([agenda, convertir], 'convertir des devises'), [convertir])
})

test('ce qui est cherché ne contient jamais une valeur', () => {
  assert.ok(!searchableText(convertir).includes('SECRETE'))
  assert.deepEqual(filterLocally([convertir], 'VALEUR-SECRETE'), [])
})

test('le serveur n’est interrogé que pour une vraie recherche parmi beaucoup d’outils', () => {
  assert.equal(needsServerSearch('c', 50), false)
  assert.equal(needsServerSearch('devise', 7), false)
  assert.equal(needsServerSearch('devise', 8), true)
})
