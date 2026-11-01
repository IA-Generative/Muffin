// What a run is doing, step by step, as the chat shows it while it goes on: the run's events (the same ones the execution panel
// lists afterwards) read as lines - "Analyse de la question", then what it decided, "Recherche dans Procédures RH", how many passages...

export interface RunEvent {
  id: string
  type: string
  taskId?: string | null
  data?: Record<string, unknown> | null
  createdAt: string
}

export type StepState = 'running' | 'done' | 'failed'

export interface LiveStep {
  // What a pair of events (started, completed) is about: the second one updates the line of the first.
  key: string
  label: string
  detail?: string
  state: StepState
  at: string
}

const plural = (count: number, one: string, many: string) => `${count} ${count > 1 ? many : one}`

const names = (value: unknown): string[] => (Array.isArray(value) ? value.map(String).filter(Boolean) : [])

const asNumber = (value: unknown): number | undefined => (typeof value === 'number' ? value : undefined)

const clip = (text: string, max = 80) => (text.length > max ? `${text.slice(0, max - 1)}…` : text)

// What the plan decided, in one line.
export function describePlan(analysis: Record<string, unknown> | undefined): string | undefined {
  if (!analysis) return undefined
  const queries = Array.isArray(analysis.queries) ? (analysis.queries as { query?: string }[]) : []
  switch (analysis.mode) {
    case 'direct':
      return 'Réponse directe, sans consulter vos documents'
    case 'clarify':
      return 'Une précision est nécessaire'
    case 'help':
      return "Question sur l'utilisation de l'application"
    case 'edit':
      return 'Modification d’un document'
    case 'create':
      return 'Création d’un document'
    case 'search': {
      const asked = queries.map((item) => item.query).filter((query): query is string => !!query)
      const where = names(analysis.collections).length
        ? ` · ${plural(names(analysis.collections).length, 'collection choisie', 'collections choisies')}`
        : ' · toutes vos collections'
      return `${plural(asked.length || 1, 'recherche', 'recherches')}${where}`
    }
    default:
      return undefined
  }
}

interface Line {
  key: string
  label: string
  detail?: string
  state: StepState
}

// One event as a line, or nothing when it adds nothing to what the user reads.
export function describeEvent(event: RunEvent): Line | undefined {
  const data = event.data ?? {}
  const task = event.taskId ?? ''
  switch (event.type) {
    case 'run_started':
      return { key: 'run', label: 'Recherche démarrée', state: 'done' }
    case 'vdb_discovery_started':
      return { key: 'vdb', label: 'Vos collections accessibles', state: 'running' }
    case 'vdb_discovery_completed': {
      const count = asNumber(data.accessible_count)
      return {
        key: 'vdb',
        label: 'Vos collections accessibles',
        detail: count === undefined ? undefined : plural(count, 'collection', 'collections'),
        state: 'done',
      }
    }
    case 'query_analysis_started':
      return { key: 'plan', label: 'Analyse de la question', state: 'running' }
    case 'query_analysis_completed':
      return {
        key: 'plan',
        label: 'Analyse de la question',
        detail: describePlan(data.analysis as Record<string, unknown> | undefined),
        state: 'done',
      }
    case 'task_started':
      return {
        key: `task:${task}`,
        label: `Recherche : « ${clip(String(data.query ?? ''))} »`,
        state: 'running',
      }
    case 'vdb_routing_completed': {
      const where = names(data.selected)
      return where.length ? { key: `task:${task}:where`, label: `Dans ${where.join(', ')}`, state: 'done' } : undefined
    }
    case 'task_completed': {
      const count = asNumber(data.evidence_count)
      return {
        key: `task:${task}`,
        label: '',
        detail: count === undefined ? undefined : plural(count, 'passage trouvé', 'passages trouvés'),
        state: 'done',
      }
    }
    case 'task_failed':
      return { key: `task:${task}`, label: '', detail: 'La recherche a échoué', state: 'failed' }
    case 'evidence_updated': {
      const count = asNumber(data.evidence_count)
      return {
        key: 'merge',
        label: 'Résultats rassemblés',
        detail: count === undefined ? undefined : plural(count, 'passage', 'passages'),
        state: 'done',
      }
    }
    case 'coverage_evaluation_started':
      return { key: 'gate', label: 'Vérification des résultats', state: 'running' }
    case 'coverage_evaluation_completed':
      return {
        key: 'gate',
        label: 'Vérification des résultats',
        detail: data.status === 'insufficient' ? 'Peu de résultats' : 'Suffisants pour répondre',
        state: 'done',
      }
    case 'search_widened':
      return { key: 'widen', label: 'Recherche élargie à toutes vos collections', state: 'running' }
    case 'answer_context_built': {
      const count = asNumber(data.evidence_count)
      return {
        key: 'context',
        label: 'Extraits retenus pour la réponse',
        detail: count === undefined ? undefined : plural(count, 'extrait', 'extraits'),
        state: 'done',
      }
    }
    case 'answer_generation_started':
      return { key: 'answer', label: 'Rédaction de la réponse', state: 'running' }
    case 'answer_generation_completed': {
      const count = asNumber(data.citation_count)
      return {
        key: 'answer',
        label: 'Rédaction de la réponse',
        detail: count ? plural(count, 'source citée', 'sources citées') : undefined,
        state: 'done',
      }
    }
    case 'guardrail_started':
      return { key: 'guardrails', label: 'Vérification de la demande', state: 'running' }
    case 'guardrail_completed':
      // Nothing of which guardrail or why: a count, and what became of the request.
      return {
        key: 'guardrails',
        label: 'Vérification de la demande',
        detail:
          data.outcome === 'continue_with_redaction'
            ? 'des éléments sensibles masqués'
            : data.outcome === 'continue_with_warning'
              ? 'avertissement'
              : data.outcome === 'block'
                ? 'demande non traitée'
                : undefined,
        state: 'done',
      }
    case 'guardrail_blocked':
      return undefined
    case 'image_reading_started': {
      const count = asNumber(data.count)
      return {
        key: 'images',
        label: 'Lecture des images jointes',
        detail: count === undefined ? undefined : plural(count, 'image', 'images'),
        state: 'done',
      }
    }
    case 'answer_model_switched':
      // The model chosen does not read images (#512): the answer is written by one that does, and it is said here.
      return {
        key: 'model',
        label: 'Réponse écrite par un modèle qui lit les images',
        detail: typeof data.to === 'string' ? data.to : undefined,
        state: 'done',
      }
    case 'edit_delegated':
      return { key: 'edit', label: 'Modification confiée à l’agent d’édition', state: 'running' }
    case 'edit_delegation_finished':
      return { key: 'edit', label: 'Modification confiée à l’agent d’édition', detail: 'Proposition prête', state: 'done' }
    case 'edit_refused':
      return { key: 'edit', label: 'Modification confiée à l’agent d’édition', detail: 'Refusée', state: 'failed' }
    case 'create_delegated':
      return { key: 'create', label: 'Rédaction du document', state: 'running' }
    case 'create_proposed':
      return { key: 'create', label: 'Rédaction du document', detail: 'Proposition prête', state: 'done' }
    case 'create_failed':
      return { key: 'create', label: 'Rédaction du document', detail: 'Échec', state: 'failed' }
    case 'clarification_requested':
      return { key: 'ask', label: 'Questions posées', state: 'done' }
    case 'help_answer_started':
      return { key: 'help', label: 'Recherche dans l’aide', state: 'running' }
    case 'help_answer_completed':
      return { key: 'help', label: 'Recherche dans l’aide', state: 'done' }
    case 'run_failed':
      return { key: 'run:failed', label: 'La recherche a échoué', state: 'failed' }
    default:
      return undefined
  }
}

// The steps once these events are known: a completed event updates the line its started one made (keeping its label when it has
// none), any other adds a line. Pure: returns a new list.
export function applyEvents(steps: LiveStep[], events: RunEvent[]): LiveStep[] {
  const next = steps.map((step) => ({ ...step }))
  for (const event of events) {
    const line = describeEvent(event)
    if (!line) continue
    const found = next.find((step) => step.key === line.key)
    if (found) {
      found.label = line.label || found.label
      found.detail = line.detail ?? found.detail
      found.state = line.state
    } else {
      next.push({ ...line, at: event.createdAt })
    }
  }
  return next
}
