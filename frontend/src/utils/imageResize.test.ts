import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ACCEPTED_TYPES, fitWithin, imagesOf, isAcceptedImage } from './imageResize.ts'

test('une image dans les bornes garde ses dimensions, et on ne l’agrandit jamais', () => {
  assert.deepEqual(fitWithin(800, 600, 2048), { width: 800, height: 600 })
  assert.deepEqual(fitWithin(2048, 1000, 2048), { width: 2048, height: 1000 })
})

test('une image trop grande est réduite sur son plus grand côté, proportions gardées', () => {
  assert.deepEqual(fitWithin(4096, 2048, 2048), { width: 2048, height: 1024 })
  assert.deepEqual(fitWithin(1000, 8000, 2000), { width: 250, height: 2000 })
})

test('une image très étroite garde au moins un pixel', () => {
  assert.deepEqual(fitWithin(10000, 1, 2048), { width: 2048, height: 1 })
})

test('seuls le PNG, le JPEG et le WebP sont acceptés, jamais un SVG ni un GIF', () => {
  assert.deepEqual(ACCEPTED_TYPES, ['image/png', 'image/jpeg', 'image/webp'])
  assert.equal(isAcceptedImage({ type: 'image/png' }), true)
  assert.equal(isAcceptedImage({ type: 'image/svg+xml' }), false)
  assert.equal(isAcceptedImage({ type: 'image/gif' }), false)
  assert.equal(isAcceptedImage({ type: 'application/pdf' }), false)
})

test('on ne garde d’un presse-papiers ou d’un dépôt que les images', () => {
  const files = [{ type: 'image/png' }, { type: 'text/plain' }, { type: 'image/webp' }] as File[]
  assert.equal(imagesOf(files).length, 2)
  assert.deepEqual(imagesOf(null), [])
  assert.deepEqual(imagesOf(undefined), [])
})
