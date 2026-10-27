import assert from 'node:assert/strict'
import { test } from 'node:test'
import { bulbSeconds, foldFull, formatBytes, formatDuration, formatEnergy, phoneCharges } from './execution.ts'

test('formatDuration goes from milliseconds to hours', () => {
  assert.equal(formatDuration(0.25), '250 ms')
  assert.equal(formatDuration(4.26), '4,3 s')
  assert.equal(formatDuration(42), '42 s')
  assert.equal(formatDuration(245), '4 min 05 s')
  assert.equal(formatDuration(7380), '2 h 03 min')
})

test('formatBytes shows nothing for a node, which holds no memory of its own', () => {
  assert.equal(formatBytes(0), '–')
  assert.equal(formatBytes(512_000_000), '512 Mo')
  assert.equal(formatBytes(1_500_000_000), '1,50 Go')
})

test('formatEnergy never shows zero for a task that did consume', () => {
  assert.equal(formatEnergy(0), '0 Wh')
  assert.equal(formatEnergy(0.004), '< 0,01 Wh')
  assert.equal(formatEnergy(0.256), '0,26 Wh')
  assert.equal(formatEnergy(12.34), '12,3 Wh')
  assert.equal(formatEnergy(1500), '1,50 kWh')
})

test('an energy is pictured as the time a LED bulb stays lit and as the charge of a smartphone', () => {
  assert.equal(bulbSeconds(1), 360) // 1 Wh keeps a 10 W bulb lit 6 minutes
  assert.equal(bulbSeconds(0), 0)
  assert.equal(phoneCharges(13), 1)
  assert.equal(phoneCharges(6.5), 0.5)
})

test('foldFull hides only the full items, never the one still filling', () => {
  assert.deepEqual(foldFull(3, 6), { folded: 0, shown: 3 })
  assert.deepEqual(foldFull(6, 6), { folded: 0, shown: 6 })
  assert.deepEqual(foldFull(20, 6), { folded: 14, shown: 6 })
})
