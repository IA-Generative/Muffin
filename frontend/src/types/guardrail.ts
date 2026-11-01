export type GuardrailType = 'rules' | 'llm' | 'http'
export type Enforcement = 'block' | 'warn' | 'redact' | 'monitor'
export type OnError = 'fail_open' | 'fail_closed'
export type Aggregation = 'any' | 'quorum'
export type WaitStrategy = 'wait_all' | 'first_block'
export type OnIncomplete = 'continue' | 'block'

export interface RulesConfig {
  builtins?: string[]
  patterns?: { name: string; regex: string; label?: string }[]
  terms?: string[]
  max_chars?: number | null
  category?: string | null
}

export interface LlmConfig {
  prompt?: string
  categories?: string[]
  threshold?: number
  model?: string | null
}

export interface HttpConfig {
  url?: string
}

export interface Guardrail {
  id: string
  name: string
  description: string
  type: GuardrailType
  config: RulesConfig & LlmConfig & HttpConfig
  enabled: boolean
  enforcement: Enforcement
  stage: number
  timeoutMs: number
  onError: OnError
  critical: boolean
  scopeGroups: string[]
  scopeAssistants: string[]
  refusalMessage: string | null
  categoryLabel: string | null
  // Une clé est enregistrée pour le service ; on ne la relit jamais.
  hasKey: boolean
  presetKey: string | null
  position: number
  version: number
  updatedAt: string
}

// Ce que l'administrateur règle ; la clé n'est envoyée que quand on en saisit une.
export interface GuardrailDraft {
  name: string
  description: string
  type: GuardrailType
  config: RulesConfig & LlmConfig & HttpConfig
  enabled: boolean
  enforcement: Enforcement
  stage: number
  timeoutMs: number
  onError: OnError
  critical: boolean
  scopeGroups: string[]
  scopeAssistants: string[]
  refusalMessage: string
  categoryLabel: string
  apiKey: string
  clearKey: boolean
}

export interface GuardrailPolicy {
  aggregation: Aggregation
  quorum: number
  waitStrategy: WaitStrategy
  timeoutMs: number
  onIncomplete: OnIncomplete
  minVerdicts: number
  showCategory: boolean
  defaultRefusal: string
}

export interface ProbeVerdict {
  guardrailId: string | null
  name: string
  enabled: boolean
  stage: number
  enforcement: Enforcement
  verdict: string
  category: string | null
  score: number | null
  latencyMs: number
  action: string
}

export interface ProbeResult {
  outcome: string
  message: string | null
  text: string
  incomplete: boolean
  verdicts: ProbeVerdict[]
}

export interface GuardrailStatRow {
  guardrailId: string | null
  name: string
  day: string
  evaluated: number
  flagged: number
  blocked: number
  failed: number
  avgLatencyMs: number
  maxLatencyMs: number
}

export interface GuardrailStats {
  days: number
  requestsChecked: number
  requestsBlocked: number
  rows: GuardrailStatRow[]
}

export interface GuardrailAuditEntry {
  id: string
  guardrailName: string
  action: string
  userDisplay: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  createdAt: string
}
