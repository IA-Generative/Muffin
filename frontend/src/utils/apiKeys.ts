// The personal API keys (#521): what the page of the keys shows of each.

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  scopes: string[]
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export type ApiKeyStatus = 'active' | 'revoked' | 'expired'

export function apiKeyStatus(key: ApiKey, now: Date = new Date()): ApiKeyStatus {
  if (key.revoked_at) return 'revoked'
  return new Date(key.expires_at) <= now ? 'expired' : 'active'
}

export const SCOPE_LABELS: Record<string, string> = {
  search: 'Recherche (serveur MCP)',
  chat: 'Discussion (API compatible OpenAI)',
}

export function scopeLabel(scope: string): string {
  return SCOPE_LABELS[scope] ?? scope
}

// The days left before a key expires, rounded up: "0" is only for one that is past.
export function daysLeft(key: ApiKey, now: Date = new Date()): number {
  const ms = new Date(key.expires_at).getTime() - now.getTime()
  return ms <= 0 ? 0 : Math.ceil(ms / 86_400_000)
}
