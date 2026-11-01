import type {
  Enforcement,
  Guardrail,
  GuardrailAuditEntry,
  GuardrailDraft,
  GuardrailStatRow,
  GuardrailType,
} from '../types/guardrail'

export const BUILTINS: { key: string; label: string; hint: string }[] = [
  { key: 'email', label: 'Adresses e-mail', hint: 'jean.dupont@exemple.fr' },
  { key: 'phone_fr', label: 'Téléphones français', hint: '06 12 34 56 78, +33 1 23 45 67 89' },
  { key: 'iban', label: 'IBAN', hint: 'contrôlé par sa clé : un numéro qui y ressemble seulement n’en est pas un' },
  { key: 'nir', label: 'Numéro de sécurité sociale (NIR)', hint: 'contrôlé par sa clé' },
  { key: 'secret', label: 'Secrets et clés d’API', hint: 'sk-…, AKIA…, jetons, clés privées, « password = … »' },
]

export const TYPE_LABELS: Record<GuardrailType, string> = {
  rules: 'Règles (code)',
  llm: 'Modèle (juge)',
  http: 'Service externe',
}

export const ENFORCEMENT_LABELS: Record<Enforcement, string> = {
  block: 'Bloquer',
  warn: 'Avertir',
  redact: 'Masquer',
  monitor: 'Observer',
}

export const ENFORCEMENT_HINTS: Record<Enforcement, string> = {
  block: 'La demande s’arrête ici ; la personne lit un refus.',
  warn: 'La demande continue ; la personne est prévenue.',
  redact: 'Le texte sensible est masqué avant d’aller au modèle ; la demande continue.',
  monitor: 'Rien n’est visible de la personne : le verdict est seulement enregistré (pour mesurer les faux positifs).',
}

const VERDICTS: Record<string, string> = {
  clear: 'RAS',
  flagged: 'Signalé',
  error: 'Erreur',
  timeout: 'Trop lent',
  cancelled: 'Annulé',
  not_run: 'Non exécuté',
}

export function verdictLabel(verdict: string): string {
  return VERDICTS[verdict] ?? verdict
}

const ACTIONS: Record<string, string> = {
  blocked: 'a bloqué',
  redacted: 'a masqué',
  warned: 'a averti',
  monitored: 'observé',
  ignored: 'panne ignorée',
  none: '—',
}

export function actionLabel(action: string): string {
  return ACTIONS[action] ?? action
}

const OUTCOMES: Record<string, string> = {
  continue: 'La demande continue',
  continue_with_redaction: 'La demande continue, masquée',
  continue_with_warning: 'La demande continue, avec un avertissement',
  block: 'La demande est bloquée',
}

export function outcomeLabel(outcome: string): string {
  return OUTCOMES[outcome] ?? outcome
}

export function emptyDraft(type: GuardrailType = 'rules'): GuardrailDraft {
  const config =
    type === 'rules'
      ? { builtins: [], patterns: [], terms: [], max_chars: null, category: '' }
      : type === 'llm'
        ? { prompt: '', categories: [], threshold: 0.5, model: '' }
        : { url: '' }
  return {
    name: '',
    description: '',
    type,
    config,
    enabled: false,
    enforcement: 'monitor',
    stage: type === 'rules' ? 1 : 2,
    timeoutMs: 2000,
    onError: 'fail_open',
    critical: false,
    scopeGroups: [],
    scopeAssistants: [],
    refusalMessage: '',
    categoryLabel: '',
    apiKey: '',
    clearKey: false,
  }
}

export function draftOf(guardrail: Guardrail): GuardrailDraft {
  return {
    name: guardrail.name,
    description: guardrail.description,
    type: guardrail.type,
    config: JSON.parse(JSON.stringify(guardrail.config)),
    enabled: guardrail.enabled,
    enforcement: guardrail.enforcement,
    stage: guardrail.stage,
    timeoutMs: guardrail.timeoutMs,
    onError: guardrail.onError,
    critical: guardrail.critical,
    scopeGroups: [...guardrail.scopeGroups],
    scopeAssistants: [...guardrail.scopeAssistants],
    refusalMessage: guardrail.refusalMessage ?? '',
    categoryLabel: guardrail.categoryLabel ?? '',
    apiKey: '',
    clearKey: false,
  }
}

// Une liste saisie en lignes ou séparée par des virgules → ses éléments, sans vide ni doublon.
export function splitList(text: string): string[] {
  return [...new Set(text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]
}

// La configuration telle que le serveur la lit : sans ce qui est vide, pour qu'un champ laissé blanc ne compte pas.
export function cleanConfig(type: GuardrailType, config: GuardrailDraft['config']): GuardrailDraft['config'] {
  if (type === 'rules') {
    return {
      builtins: config.builtins ?? [],
      patterns: (config.patterns ?? []).filter((pattern) => pattern.regex.trim()),
      terms: (config.terms ?? []).map((term) => term.trim()).filter(Boolean),
      max_chars: config.max_chars ? Number(config.max_chars) : null,
      ...(config.category?.trim() ? { category: config.category.trim() } : {}),
    }
  }
  if (type === 'llm') {
    return {
      ...(config.prompt?.trim() ? { prompt: config.prompt.trim() } : {}),
      categories: config.categories ?? [],
      threshold: Number(config.threshold ?? 0.5),
      ...(config.model?.trim() ? { model: config.model.trim() } : {}),
    }
  }
  return { url: (config.url ?? '').trim() }
}

// Un motif de l'éditeur essayé sur un texte, dans le navigateur. Le serveur reste juge : il lit les motifs avec Python,
// dont la syntaxe n'est pas tout à fait celle de JavaScript.
export function tryPattern(regex: string, sample: string): { valid: boolean; matches: number } {
  if (!regex) return { valid: true, matches: 0 }
  try {
    const found = sample.match(new RegExp(regex, 'g'))
    return { valid: true, matches: found ? found.length : 0 }
  } catch {
    return { valid: false, matches: 0 }
  }
}

export interface GuardrailTotals {
  name: string
  evaluated: number
  flagged: number
  blocked: number
  failed: number
  avgLatencyMs: number
  blockRate: number
}

// Les lignes par jour, additionnées par garde-fou : comptes et temps, jamais de texte.
export function totalsByGuardrail(rows: GuardrailStatRow[]): GuardrailTotals[] {
  const byName = new Map<string, GuardrailTotals & { weighted: number }>()
  for (const row of rows) {
    const total = byName.get(row.name) ?? {
      name: row.name,
      evaluated: 0,
      flagged: 0,
      blocked: 0,
      failed: 0,
      avgLatencyMs: 0,
      blockRate: 0,
      weighted: 0,
    }
    total.evaluated += row.evaluated
    total.flagged += row.flagged
    total.blocked += row.blocked
    total.failed += row.failed
    total.weighted += row.avgLatencyMs * row.evaluated
    byName.set(row.name, total)
  }
  return [...byName.values()]
    .map(({ weighted, ...total }) => ({
      ...total,
      avgLatencyMs: total.evaluated ? Math.round(weighted / total.evaluated) : 0,
      blockRate: total.evaluated ? total.blocked / total.evaluated : 0,
    }))
    .sort((a, b) => b.evaluated - a.evaluated || a.name.localeCompare(b.name))
}

const FIELD_LABELS: Record<string, string> = {
  name: 'nom',
  description: 'description',
  config: 'réglages',
  enabled: 'activé',
  enforcement: 'mode',
  stage: 'étape',
  timeout_ms: 'délai',
  on_error: 'en cas d’erreur',
  critical: 'critique',
  scope_groups: 'groupes',
  scope_assistants: 'assistants',
  refusal_message: 'message',
  category_label: 'catégorie',
  has_key: 'clé',
  version: 'version',
  aggregation: 'agrégation',
  quorum: 'quorum',
  wait_strategy: 'attente',
  on_incomplete: 'si incomplet',
  min_verdicts: 'verdicts exigés',
  show_category: 'catégorie dans le refus',
  default_refusal: 'refus par défaut',
}

// Ce qui a changé dans une entrée du journal : « mode : monitor → block ». La version ne compte pas comme un changement.
export function describeChanges(entry: GuardrailAuditEntry): string[] {
  if (entry.action === 'created') return ['créé']
  if (entry.action === 'deleted') return ['supprimé']
  if (entry.action === 'reordered') return ['ordre modifié']
  const before = entry.before ?? {}
  const after = entry.after ?? {}
  return Object.keys(after)
    .filter((key) => key !== 'version' && JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => {
      const label = FIELD_LABELS[key] ?? key
      if (key === 'config') return `${label} modifiés`
      return `${label} : ${display(before[key])} → ${display(after[key])}`
    })
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'oui' : 'non'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
  return String(value)
}
