import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chartAltText, chartImageUrl } from './chartImages.ts'

const API = 'https://muffin.example.fr'
const PATH = '/api/conversations/6f1c2a4e-1b7d-4c0e-9a55-0d2f3b4c5d6e/charts/0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d.png'

test('a chart of the backend is loaded from the API', () => {
  assert.equal(chartImageUrl(PATH, API), `${API}${PATH}`)
  assert.equal(chartImageUrl(PATH, `${API}/`), `${API}${PATH}`)
})

test('the address the API already gave in full is accepted as it is', () => {
  assert.equal(chartImageUrl(`${API}${PATH}`, API), `${API}${PATH}`)
})

test('an image from anywhere else is refused', () => {
  const refused = [
    `https://evil.example/pixel.png?data=secret`,
    `//evil.example${PATH}`,
    `https://evil.example${PATH}`,
    `${API}.evil.example${PATH}`,
    'data:image/png;base64,AAAA',
    'javascript:alert(1)',
    '/api/conversations/x/charts/y.png',
    `${PATH}?x=https://evil.example`,
    `${PATH}/../../../secret.png`,
    `/other${PATH}`,
    '',
  ]
  for (const src of refused) assert.equal(chartImageUrl(src, API), null, src)
})

test('the alternative text is the title of the chart', () => {
  assert.equal(chartAltText('Total par région'), 'Graphique : Total par région')
  assert.equal(chartAltText('  '), 'Graphique')
  assert.equal(chartAltText(null), 'Graphique')
})
