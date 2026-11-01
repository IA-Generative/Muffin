import { ref } from 'vue'
import type {
  Guardrail,
  GuardrailAuditEntry,
  GuardrailDraft,
  GuardrailPolicy,
  GuardrailStats,
  ProbeResult,
} from '../types/guardrail'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface GuardrailOut {
  id: string
  name: string
  description: string
  type: Guardrail['type']
  config: Guardrail['config']
  enabled: boolean
  enforcement: Guardrail['enforcement']
  stage: number
  timeout_ms: number
  on_error: Guardrail['onError']
  critical: boolean
  scope_groups: string[]
  scope_assistants: string[]
  refusal_message: string | null
  category_label: string | null
  has_key: boolean
  preset_key: string | null
  position: number
  version: number
  updated_at: string
}

interface PolicyOut {
  aggregation: GuardrailPolicy['aggregation']
  quorum: number
  wait_strategy: GuardrailPolicy['waitStrategy']
  timeout_ms: number
  on_incomplete: GuardrailPolicy['onIncomplete']
  min_verdicts: number
  show_category: boolean
  default_refusal: string
}

function toGuardrail(raw: GuardrailOut): Guardrail {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    type: raw.type,
    config: raw.config,
    enabled: raw.enabled,
    enforcement: raw.enforcement,
    stage: raw.stage,
    timeoutMs: raw.timeout_ms,
    onError: raw.on_error,
    critical: raw.critical,
    scopeGroups: raw.scope_groups,
    scopeAssistants: raw.scope_assistants,
    refusalMessage: raw.refusal_message,
    categoryLabel: raw.category_label,
    hasKey: raw.has_key,
    presetKey: raw.preset_key,
    position: raw.position,
    version: raw.version,
    updatedAt: raw.updated_at,
  }
}

function toPolicy(raw: PolicyOut): GuardrailPolicy {
  return {
    aggregation: raw.aggregation,
    quorum: raw.quorum,
    waitStrategy: raw.wait_strategy,
    timeoutMs: raw.timeout_ms,
    onIncomplete: raw.on_incomplete,
    minVerdicts: raw.min_verdicts,
    showCategory: raw.show_category,
    defaultRefusal: raw.default_refusal,
  }
}

// Le corps d'une création ou d'une modification. La clé n'est envoyée que saisie ; « oublier la clé » est un ordre à part.
function toBody(draft: GuardrailDraft, creating: boolean) {
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    ...(creating ? { type: draft.type } : {}),
    config: draft.config,
    enabled: draft.enabled,
    enforcement: draft.enforcement,
    stage: draft.stage,
    timeout_ms: draft.timeoutMs,
    on_error: draft.onError,
    critical: draft.critical,
    scope_groups: draft.scopeGroups,
    scope_assistants: draft.scopeAssistants,
    refusal_message: draft.refusalMessage.trim() || undefined,
    category_label: draft.categoryLabel.trim() || undefined,
    ...(creating
      ? {}
      : { clear_refusal_message: !draft.refusalMessage.trim(), clear_category_label: !draft.categoryLabel.trim() }),
    ...(draft.apiKey.trim() ? { api_key: draft.apiKey.trim() } : {}),
    ...(draft.clearKey ? { clear_key: true } : {}),
  }
}

async function refusal(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
    if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === 'string') return body.detail[0].msg
  } catch {
    // Pas de corps à lire.
  }
  return fallback
}

const guardrails = ref<Guardrail[]>([])
const policy = ref<GuardrailPolicy | null>(null)
const stats = ref<GuardrailStats | null>(null)
const audit = ref<GuardrailAuditEntry[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function call(path: string, method = 'GET', body?: unknown): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/admin/guardrails${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

async function loadGuardrails() {
  isLoading.value = true
  error.value = null
  try {
    const [list, policyResponse] = await Promise.all([call(''), call('/policy')])
    if (!list.ok || !policyResponse.ok) throw new Error('refused')
    guardrails.value = (await list.json()).map(toGuardrail)
    policy.value = toPolicy(await policyResponse.json())
  } catch {
    error.value = 'Impossible de récupérer les garde-fous.'
  } finally {
    isLoading.value = false
  }
}

// `null` quand c'est fait, le message du refus sinon.
async function save(draft: GuardrailDraft, id?: string): Promise<string | null> {
  const response = await call(id ? `/${id}` : '', id ? 'PATCH' : 'POST', toBody(draft, !id))
  if (!response.ok) return refusal(response, 'Impossible d’enregistrer le garde-fou.')
  await Promise.all([loadGuardrails(), loadAudit()])
  return null
}

async function patch(id: string, changes: Record<string, unknown>): Promise<string | null> {
  const response = await call(`/${id}`, 'PATCH', changes)
  if (!response.ok) return refusal(response, 'Impossible de modifier le garde-fou.')
  await Promise.all([loadGuardrails(), loadAudit()])
  return null
}

async function remove(id: string): Promise<string | null> {
  const response = await call(`/${id}`, 'DELETE')
  if (!response.ok) return refusal(response, 'Impossible de supprimer le garde-fou.')
  await Promise.all([loadGuardrails(), loadAudit()])
  return null
}

async function reorder(ids: string[]): Promise<string | null> {
  const response = await call('/reorder', 'POST', { ids })
  if (!response.ok) return refusal(response, 'Impossible de changer l’ordre.')
  guardrails.value = (await response.json()).map(toGuardrail)
  await loadAudit()
  return null
}

async function savePolicy(draft: GuardrailPolicy): Promise<string | null> {
  const response = await call('/policy', 'PATCH', {
    aggregation: draft.aggregation,
    quorum: draft.quorum,
    wait_strategy: draft.waitStrategy,
    timeout_ms: draft.timeoutMs,
    on_incomplete: draft.onIncomplete,
    min_verdicts: draft.minVerdicts,
    show_category: draft.showCategory,
    default_refusal: draft.defaultRefusal,
  })
  if (!response.ok) return refusal(response, 'Impossible d’enregistrer la politique.')
  policy.value = toPolicy(await response.json())
  await loadAudit()
  return null
}

// Ce que chaque garde-fou dit d'un texte tapé ici : rien n'est gardé, aucun run n'est fait.
async function probe(text: string): Promise<{ result: ProbeResult | null; message: string | null }> {
  try {
    const response = await call('/test', 'POST', { text })
    if (!response.ok) return { result: null, message: await refusal(response, 'Impossible d’essayer ce texte.') }
    const raw = await response.json()
    return {
      message: null,
      result: {
        outcome: raw.outcome,
        message: raw.message,
        text: raw.text,
        incomplete: raw.incomplete,
        verdicts: raw.verdicts.map(
          (item: {
            guardrail_id: string | null
            name: string
            enabled: boolean
            stage: number
            enforcement: ProbeResult['verdicts'][number]['enforcement']
            verdict: string
            category: string | null
            score: number | null
            latency_ms: number
            action: string
          }) => ({
            guardrailId: item.guardrail_id,
            name: item.name,
            enabled: item.enabled,
            stage: item.stage,
            enforcement: item.enforcement,
            verdict: item.verdict,
            category: item.category,
            score: item.score,
            latencyMs: item.latency_ms,
            action: item.action,
          }),
        ),
      },
    }
  } catch {
    return { result: null, message: 'Le serveur est inaccessible.' }
  }
}

async function loadStats(days = 30) {
  try {
    const response = await call(`/stats?days=${days}`)
    if (!response.ok) return
    const raw = await response.json()
    stats.value = {
      days: raw.days,
      requestsChecked: raw.requests_checked,
      requestsBlocked: raw.requests_blocked,
      rows: raw.rows.map(
        (row: {
          guardrail_id: string | null
          name: string
          day: string
          evaluated: number
          flagged: number
          blocked: number
          failed: number
          avg_latency_ms: number
          max_latency_ms: number
        }) => ({
          guardrailId: row.guardrail_id,
          name: row.name,
          day: row.day,
          evaluated: row.evaluated,
          flagged: row.flagged,
          blocked: row.blocked,
          failed: row.failed,
          avgLatencyMs: row.avg_latency_ms,
          maxLatencyMs: row.max_latency_ms,
        }),
      ),
    }
  } catch {
    // Les chiffres ne sont pas indispensables : la page reste utilisable.
  }
}

async function loadAudit() {
  try {
    const response = await call('/audit?page_size=20')
    if (!response.ok) return
    audit.value = (await response.json()).items.map(
      (item: {
        id: string
        guardrail_name: string
        action: string
        user_display: string
        before: Record<string, unknown> | null
        after: Record<string, unknown> | null
        created_at: string
      }) => ({
        id: item.id,
        guardrailName: item.guardrail_name,
        action: item.action,
        userDisplay: item.user_display,
        before: item.before,
        after: item.after,
        createdAt: item.created_at,
      }),
    )
  } catch {
    // Le journal est un confort : pas d'erreur bloquante.
  }
}

export function useAdminGuardrails() {
  return {
    guardrails,
    policy,
    stats,
    audit,
    isLoading,
    error,
    loadGuardrails,
    loadStats,
    loadAudit,
    save,
    patch,
    remove,
    reorder,
    savePolicy,
    probe,
  }
}
