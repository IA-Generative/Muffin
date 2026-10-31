import assert from 'node:assert/strict'
import { test } from 'node:test'
import { type ApiKey, apiKeyStatus, daysLeft, scopeLabel } from './apiKeys.ts'

const NOW = new Date('2026-11-17T12:00:00Z')

function key(overrides: Partial<ApiKey> = {}): ApiKey {
  return {
    id: 'k1',
    name: 'script',
    key_prefix: 'sk-muffin-AbCdEf',
    scopes: ['search'],
    created_at: '2026-11-01T00:00:00Z',
    expires_at: '2027-02-15T12:00:00Z',
    last_used_at: null,
    revoked_at: null,
    ...overrides,
  }
}

test('a key that is neither revoked nor past its date is active', () => {
  assert.equal(apiKeyStatus(key(), NOW), 'active')
})

test('a key past its date is expired', () => {
  assert.equal(apiKeyStatus(key({ expires_at: '2026-11-17T11:59:59Z' }), NOW), 'expired')
})

test('a revoked key is revoked, even before its date and after it', () => {
  assert.equal(apiKeyStatus(key({ revoked_at: '2026-11-10T00:00:00Z' }), NOW), 'revoked')
  assert.equal(
    apiKeyStatus(key({ revoked_at: '2026-11-10T00:00:00Z', expires_at: '2026-11-11T00:00:00Z' }), NOW),
    'revoked',
  )
})

test('the days left are rounded up and never negative', () => {
  assert.equal(daysLeft(key({ expires_at: '2026-11-17T12:00:01Z' }), NOW), 1)
  assert.equal(daysLeft(key({ expires_at: '2026-11-19T12:00:00Z' }), NOW), 2)
  assert.equal(daysLeft(key({ expires_at: '2026-11-01T00:00:00Z' }), NOW), 0)
})

test('a scope the page does not know is shown as it is', () => {
  assert.equal(scopeLabel('search'), 'Recherche (serveur MCP)')
  assert.equal(scopeLabel('future'), 'future')
})
