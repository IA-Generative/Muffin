import { computed, ref } from 'vue'
import { router } from '../router'
import type { ChatMessage, Conversation, ExecutionEvent, FeedbackDetails, Source } from '../types/chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

// Backend response shapes (snake_case) - see backend/app/schemas/conversation.py and run.py.
interface ConversationOut {
  id: string
  title: string | null
  updated_at: string
}

interface MessageOut {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

interface RunEventOut {
  id: string
  task_id: string | null
  type: string
  data: Record<string, unknown> | null
  created_at: string
}

interface RunOut {
  id: string
  conversation_id: string | null
  status: string
  current_activity: string | null
  pending_human_action: { question?: string } | null
  answer: string | null
  citations: { evidence_id: string; source: string | null; vdb_id: string }[] | null
  error: string | null
}

// Module-level singleton, comme useTheme : partagé entre la sidebar (liste des
// conversations) et la zone de chat (messages), sans prop-drilling via App.vue.
const conversations = ref<Conversation[]>([{ id: 'default', title: 'Nouvelle conversation' }])
const activeId = ref('default')
const messagesByConversation = ref<Record<string, ChatMessage[]>>({ default: [] })
const activeSourcesMessageId = ref<string>()
const activeExecutionMessageId = ref<string>()
const executionEventsByMessageId = ref<Record<string, ExecutionEvent[]>>({})
// The sidebar starts a conversation under a client-side placeholder id (no
// GET /api/conversations to fetch a real one from yet); the first run made
// in it returns the real backend conversation id, which the placeholder is
// then renamed to everywhere (sidebar entry, message list, URL) via
// migrateConversationId/resolveConversationId below - so /c/<id> reflects a
// real, bookmarkable conversation as soon as one exists, not the placeholder.
const confirmedConversationIds = new Set<string>()
const conversationAliases: Record<string, string> = {}
const activePolls = new Map<string, ReturnType<typeof setInterval>>()
// A run paused on a clarification question (HITL, §31): the next message typed in this
// conversation answers it (POST /api/runs/{runId}/resume) instead of starting a new run.
const pendingClarifications: Record<string, { runId: string; messageId: string }> = {}
// Which conversation ids already have their message history loaded (or definitively don't exist
// on the backend) - avoids re-fetching on every sidebar click, and lets a brand-new local-only
// conversation (newConversation()) skip a fetch that would just 404.
const loadedConversationIds = new Set<string>()

function resolveConversationId(id: string): string {
  let resolved = id
  while (conversationAliases[resolved]) resolved = conversationAliases[resolved]
  return resolved
}

function migrateConversationId(placeholderId: string, realId: string): string {
  confirmedConversationIds.add(realId)
  loadedConversationIds.add(realId) // its messages are already in memory, nothing to fetch
  const currentId = resolveConversationId(placeholderId)
  if (currentId === realId) return realId

  messagesByConversation.value[realId] = [
    ...(messagesByConversation.value[realId] ?? []),
    ...(messagesByConversation.value[currentId] ?? []),
  ]
  delete messagesByConversation.value[currentId]
  conversationAliases[currentId] = realId

  const conversation = conversations.value.find((item) => item.id === currentId)
  if (conversation) conversation.id = realId
  if (activeId.value === currentId) {
    activeId.value = realId
    router.replace(`/c/${realId}`)
  }
  return realId
}

const messages = computed(() => messagesByConversation.value[activeId.value] ?? [])
const activeSources = computed(
  () => messages.value.find((message) => message.id === activeSourcesMessageId.value)?.sources,
)
const activeExecutionEvents = computed(() =>
  activeExecutionMessageId.value ? executionEventsByMessageId.value[activeExecutionMessageId.value] : undefined,
)

// Internal run_events type -> a short label a user can actually read - never the model's own
// reasoning (the backend never emits that as an event, only these fixed step names, see
// worker/agent_execution/app/graph/services/events.py).
const EVENT_LABELS: Record<string, string> = {
  run_started: 'Recherche démarrée',
  vdb_discovery_started: 'Recherche des bases de connaissances accessibles…',
  vdb_discovery_completed: 'Bases de connaissances accessibles identifiées',
  query_analysis_started: 'Analyse de la question…',
  query_analysis_completed: 'Question analysée',
  query_decomposition_started: 'Découpage de la question en sous-tâches…',
  query_decomposition_completed: 'Question découpée en sous-tâches',
  research_plan_created: 'Plan de recherche établi',
  task_started: 'Tâche de recherche démarrée',
  vdb_routing_started: 'Sélection des bases de connaissances pertinentes…',
  vdb_routing_completed: 'Bases de connaissances pertinentes sélectionnées',
  search_started: 'Recherche dans la base de connaissances…',
  search_completed: 'Résultats de recherche reçus',
  task_completed: 'Tâche de recherche terminée',
  task_failed: 'Tâche de recherche échouée',
  evidence_updated: 'Preuves mises à jour',
  coverage_evaluation_started: 'Évaluation de la couverture des preuves…',
  coverage_evaluation_completed: 'Couverture des preuves évaluée',
  replan_started: 'Re-planification ciblée…',
  replan_completed: 'Plan de recherche affiné',
  answer_context_built: 'Contexte de réponse préparé',
  answer_generation_started: 'Génération de la réponse…',
  answer_generation_completed: 'Réponse générée',
  grounding_validation_started: 'Vérification des faits de la réponse…',
  grounding_validation_completed: 'Faits de la réponse vérifiés',
  grounding_research_started: 'Recherche complémentaire pour étayer la réponse…',
  grounding_research_completed: 'Recherche complémentaire terminée',
  clarification_requested: 'Clarification demandée',
  clarification_received: 'Clarification reçue',
  run_waiting_for_user: 'En attente de votre réponse',
  run_completed: 'Recherche terminée',
  run_failed: 'Recherche échouée',
  run_cancelled: 'Recherche annulée',
}

function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replaceAll('_', ' ')
}

async function fetchRunEvents(runId: string): Promise<RunEventOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/events?page_size=200`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  const body: { items: RunEventOut[] } = await response.json()
  return body.items
}

async function fetchConversationsList(): Promise<ConversationOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/conversations?page_size=100`, { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status}`)
  const body: { items: ConversationOut[] } = await response.json()
  return body.items
}

async function fetchMessagesList(conversationId: string): Promise<MessageOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/messages`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
}

// Restores a conversation's history on first visit (sidebar click, or a bookmarked /c/<id>
// reload) - a no-op once loaded. A 404 means this id never became a real backend conversation
// (e.g. a local-only placeholder from before a reload wiped module state) - starts it fresh
// rather than surfacing an error the user can't do anything about.
async function ensureMessagesLoaded(conversationId: string) {
  if (loadedConversationIds.has(conversationId)) return
  loadedConversationIds.add(conversationId)
  try {
    const items = await fetchMessagesList(conversationId)
    messagesByConversation.value[conversationId] = items.map((item) => ({
      id: item.id,
      role: item.role,
      content: item.content,
    }))
    confirmedConversationIds.add(conversationId)
  } catch {
    if (!messagesByConversation.value[conversationId]) messagesByConversation.value[conversationId] = []
  }
}

// `navigate: false` is used when a route change already triggered this (see
// ChatView's route watcher) - pushing again there would just double the entry.
function selectConversation(id: string, options: { navigate?: boolean } = {}) {
  activeId.value = id
  if (!messagesByConversation.value[id]) messagesByConversation.value[id] = []
  ensureMessagesLoaded(id)
  const target = `/c/${id}`
  if (options.navigate !== false && router.currentRoute.value.fullPath !== target) {
    router.push(target)
  }
}

function newConversation() {
  const id = crypto.randomUUID()
  conversations.value.unshift({ id, title: 'Nouvelle conversation' })
  messagesByConversation.value[id] = []
  loadedConversationIds.add(id) // fresh and local-only - nothing to fetch, would just 404
  activeId.value = id
  router.push(`/c/${id}`)
}

// Populates the sidebar with real past conversations on load, and - only if the app opened on
// "/" with nothing typed yet, never for a bookmarked /c/<id> already being restored - takes over
// the placeholder with the most recently active one instead of starting on an empty new chat.
async function initializeConversations() {
  try {
    const items = await fetchConversationsList()
    if (items.length === 0) return

    conversations.value = items.map((item) => ({ id: item.id, title: item.title || 'Nouvelle conversation' }))
    for (const item of items) confirmedConversationIds.add(item.id)

    if (activeId.value === 'default' && (messagesByConversation.value.default ?? []).length === 0) {
      const mostRecentId = items[0].id
      await ensureMessagesLoaded(mostRecentId)
      delete messagesByConversation.value.default
      activeId.value = mostRecentId
      router.replace(`/c/${mostRecentId}`)
    }
  } catch {
    // Best-effort - the app still works with just the local placeholder conversation.
  }
}

initializeConversations()

async function createRun(conversationId: string, query: string): Promise<RunOut> {
  // Only ever send a conversation_id the backend actually confirmed exists - the sidebar's
  // placeholder id would 404 (ConversationNotFoundError), so a brand-new conversation's first
  // run omits it and lets the backend create one instead.
  const known = confirmedConversationIds.has(conversationId) ? conversationId : undefined
  const response = await fetch(`${API_BASE_URL}/api/runs`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, conversation_id: known }),
  })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
}

async function fetchRun(runId: string): Promise<RunOut> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}`, { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
}

async function resumeRun(runId: string, answer: string): Promise<RunOut> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/resume`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer }),
  })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
}

// The backend cites each claim with its evidence excerpt's raw id in brackets (e.g.
// "[f8109fc0-88cc-...]" - see generate_answer.py's system prompt), so the model's grounding
// stays verifiable server-side. Showing that literal uuid to the user is meaningless, though -
// this renumbers every distinct id into a short footnote ([1], [2], ...) in order of first
// appearance in the text, and builds the sources panel to match those same numbers.
function formatAnswerWithCitations(answer: string, citations: RunOut['citations']): [string, Source[] | undefined] {
  if (!citations?.length) return [answer, undefined]

  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]))
  const footnoteNumberById = new Map<string, number>()
  const sources: Source[] = []

  const content = answer.replace(/\[([0-9a-f-]{8,})\]/gi, (match, evidenceId: string) => {
    const citation = citationById.get(evidenceId)
    if (!citation) return match
    let footnoteNumber = footnoteNumberById.get(evidenceId)
    if (footnoteNumber === undefined) {
      footnoteNumber = sources.length + 1
      footnoteNumberById.set(evidenceId, footnoteNumber)
      const sourceTitle = citation.source ?? `Source ${citation.vdb_id}`
      sources.push({ title: `${footnoteNumber}. ${sourceTitle}` })
    }
    return `[${footnoteNumber}]`
  })

  return [content, sources.length ? sources : undefined]
}

function assistantMessageFor(id: string, run: RunOut): ChatMessage {
  if (run.status === 'waiting_for_user') {
    return {
      id,
      role: 'assistant',
      content: run.pending_human_action?.question ?? 'Pouvez-vous préciser votre demande ?',
      runId: run.id,
    }
  }
  if (!TERMINAL_STATUSES.has(run.status)) {
    return { id, role: 'assistant', content: run.current_activity ?? 'Recherche en cours…', runId: run.id }
  }
  if (run.status === 'completed') {
    const [content, sources] = formatAnswerWithCitations(
      run.answer || "Je n'ai pas trouvé de réponse dans vos collections.",
      run.citations,
    )
    return { id, role: 'assistant', content, sources, runId: run.id }
  }
  return {
    id,
    role: 'assistant',
    content: run.status === 'cancelled' ? 'Cette recherche a été annulée.' : run.error || 'Cette recherche a échoué.',
    runId: run.id,
  }
}

function replaceMessage(conversationId: string, messageId: string, message: ChatMessage) {
  const list = messagesByConversation.value[resolveConversationId(conversationId)]
  const index = list?.findIndex((item) => item.id === messageId)
  if (index !== undefined && index !== -1) list[index] = message
}

// Applies a run's latest state to its placeholder message, and returns whether polling should
// stop - either a terminal status, or waiting_for_user (§31 HITL): nothing will change there
// until the user answers, which happens through sendMessage/pendingClarifications below, not
// more polling.
function applyRunUpdate(conversationId: string, messageId: string, run: RunOut): boolean {
  replaceMessage(conversationId, messageId, assistantMessageFor(messageId, run))
  if (run.status === 'waiting_for_user') {
    pendingClarifications[resolveConversationId(conversationId)] = { runId: run.id, messageId }
    return true
  }
  return TERMINAL_STATUSES.has(run.status)
}

// Polls a run until it reaches a terminal status (or pauses for a clarification), updating the
// placeholder assistant message in place each time - same setInterval-based polling convention
// as useCollections.ts's pollDocumentsWhileProcessing.
function trackRun(conversationId: string, messageId: string, run: RunOut) {
  if (applyRunUpdate(conversationId, messageId, run)) return

  const interval = setInterval(async () => {
    try {
      const current = await fetchRun(run.id)
      if (applyRunUpdate(conversationId, messageId, current)) {
        clearInterval(interval)
        activePolls.delete(messageId)
      }
    } catch {
      clearInterval(interval)
      activePolls.delete(messageId)
      replaceMessage(conversationId, messageId, {
        id: messageId,
        role: 'assistant',
        content: 'Impossible de récupérer le résultat de cette recherche.',
      })
    }
  }, 1500)
  activePolls.set(messageId, interval)
}

async function runQuery(conversationId: string, messageId: string, query: string) {
  try {
    const run = await createRun(conversationId, query)
    const resolvedId = run.conversation_id ? migrateConversationId(conversationId, run.conversation_id) : conversationId
    trackRun(resolvedId, messageId, run)
  } catch {
    replaceMessage(conversationId, messageId, {
      id: messageId,
      role: 'assistant',
      content: 'Impossible de lancer cette recherche.',
    })
  }
}

async function resumeAndTrack(conversationId: string, runId: string, messageId: string, answer: string) {
  try {
    const run = await resumeRun(runId, answer)
    trackRun(conversationId, messageId, run)
  } catch {
    replaceMessage(conversationId, messageId, {
      id: messageId,
      role: 'assistant',
      content: 'Impossible de reprendre cette recherche.',
    })
  }
}

function sendMessage(content: string) {
  const conversationId = activeId.value

  const pending = pendingClarifications[conversationId]
  if (pending) {
    delete pendingClarifications[conversationId]
    messagesByConversation.value[conversationId].push({ id: crypto.randomUUID(), role: 'user', content })
    replaceMessage(conversationId, pending.messageId, {
      id: pending.messageId,
      role: 'assistant',
      content: 'Recherche en cours…',
    })
    resumeAndTrack(conversationId, pending.runId, pending.messageId, content)
    return
  }

  const messageId = crypto.randomUUID()
  messagesByConversation.value[conversationId].push(
    { id: crypto.randomUUID(), role: 'user', content },
    { id: messageId, role: 'assistant', content: 'Recherche en cours…' },
  )
  runQuery(conversationId, messageId, content)
}

function regenerateMessage(id: string) {
  const conversationId = activeId.value
  const list = messagesByConversation.value[conversationId]
  const index = list.findIndex((message) => message.id === id)
  if (index === -1) return
  const lastUserMessage = list
    .slice(0, index)
    .reverse()
    .find((message) => message.role === 'user')
  if (!lastUserMessage) return

  const interval = activePolls.get(id)
  if (interval) {
    clearInterval(interval)
    activePolls.delete(id)
  }
  // Regenerating (e.g. from a clarification bubble) abandons whatever run was pending - a
  // stale entry here would otherwise hijack the next normal sendMessage into "resuming" it.
  delete pendingClarifications[conversationId]
  list[index] = { id, role: 'assistant', content: 'Recherche en cours…' }
  runQuery(conversationId, id, lastUserMessage.content)
}

function sendFeedback(id: string, value: 'up' | 'down', details?: FeedbackDetails) {
  console.log('Feedback', id, value, details)
}

function showSources(id: string) {
  activeExecutionMessageId.value = undefined // the two panels share one slot, mutually exclusive
  activeSourcesMessageId.value = id
}

function closeSources() {
  activeSourcesMessageId.value = undefined
}

// Fetches the run's event trace once per message (cached in executionEventsByMessageId), then
// opens the panel - a live run (still polling) always refetches, since new events keep landing.
async function showExecutionDetails(id: string) {
  activeSourcesMessageId.value = undefined // the two panels share one slot, mutually exclusive
  activeExecutionMessageId.value = id
  const runId = messages.value.find((message) => message.id === id)?.runId
  if (!runId) return
  if (executionEventsByMessageId.value[id] && !activePolls.has(id)) return
  try {
    const items = await fetchRunEvents(runId)
    executionEventsByMessageId.value[id] = items.map((item) => ({
      id: item.id,
      label: eventLabel(item.type),
      taskId: item.task_id ?? undefined,
      createdAt: item.created_at,
    }))
  } catch {
    executionEventsByMessageId.value[id] = []
  }
}

function closeExecutionDetails() {
  activeExecutionMessageId.value = undefined
}

export function useChat() {
  return {
    conversations,
    activeId,
    messages,
    activeSources,
    activeExecutionMessageId,
    activeExecutionEvents,
    selectConversation,
    newConversation,
    sendMessage,
    regenerateMessage,
    sendFeedback,
    showSources,
    closeSources,
    showExecutionDetails,
    closeExecutionDetails,
  }
}
