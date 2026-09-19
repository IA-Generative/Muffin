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

interface Citation {
  evidence_id: string
  source: string | null
  vdb_id: string
  // Absent on citations persisted before this field set existed - treated as an old-style
  // citation with no tool/page/chunk info, never a crash.
  tool?: string
  document_id?: string | null
  chunk_id?: string | null
  page_number?: number | null
  // Only ever set on a web_search citation - a real, browsable external URL.
  url?: string | null
  query?: string
  content?: string
  // The backend Source row this citation was materialized into (see the backend's
  // SourceRepository.link_citations) - absent on a "tool" citation or one persisted before this
  // existed. See Source.id in types/chat.ts.
  source_id?: string | null
}

interface MessageOut {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  run_id: string | null
  citations: Citation[] | null
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
  current_node: string | null
  current_activity: string | null
  pending_human_action: { question?: string } | null
  answer: string | null
  citations: Citation[] | null
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
// Separate from the events map itself so a fetch failure is visibly distinct from "this run
// genuinely has no events" - both used to collapse into the same empty array, which made a real
// network/ownership error indistinguishable from an empty result in the UI (and in support).
const executionErrorMessageIds = ref(new Set<string>())
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
const activeExecutionError = computed(
  () => !!activeExecutionMessageId.value && executionErrorMessageIds.value.has(activeExecutionMessageId.value),
)

// Node name (Run.current_node, set by every node's set_activity() call - see
// worker/agent_execution/app/graph/services/events.py) -> the French label shown as the chat
// placeholder while a run is in progress. Run.current_activity itself is worker-internal English
// (used for logging/debugging), never shown as-is except for "research_task", whose activity
// *is* the task's own query text - already meaningful on its own, in whatever language the user
// asked in.
const NODE_LABELS: Record<string, string> = {
  load_context: 'Démarrage de la recherche',
  load_accessible_vdbs: 'Vérification de vos bases de connaissances accessibles',
  analyze_query: 'Analyse de votre question',
  decompose_query: 'Découpage de votre question',
  build_research_plan: 'Planification de la recherche',
  merge_evidence: 'Fusion des résultats de recherche',
  evaluate_coverage: 'Vérification de la pertinence des résultats',
  replan_research: 'Affinement du plan de recherche',
  build_answer_context: 'Préparation de la réponse',
  generate_answer: 'Génération de la réponse',
  validate_grounding: 'Vérification des faits de la réponse',
  targeted_research: "Recherche d'éléments complémentaires",
  request_clarification: 'En attente de votre précision',
}

function activityLabel(run: RunOut): string {
  if (run.current_node === 'research_task' && run.current_activity) return run.current_activity
  return (run.current_node && NODE_LABELS[run.current_node]) || run.current_activity || 'Recherche en cours'
}

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
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/events`, { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`)
  return response.json()
}

const CONVERSATIONS_PAGE_SIZE = 30

async function fetchConversationsList(page: number): Promise<{ items: ConversationOut[]; total: number }> {
  const response = await fetch(`${API_BASE_URL}/api/conversations?page=${page}&page_size=${CONVERSATIONS_PAGE_SIZE}`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  const body: { items: ConversationOut[]; total: number } = await response.json()
  return body
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
    messagesByConversation.value[conversationId] = items.map((item) => {
      const [content, sources] = formatAnswerWithCitations(item.content, item.citations)
      return {
        id: item.id,
        role: item.role,
        content,
        sources,
        runId: item.run_id ?? undefined,
      }
    })
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

async function renameConversation(id: string, title: string) {
  // Same resolution as deleteConversation - a sidebar row's id can be a pre-migration
  // placeholder still aliased to the real backend id (see migrateConversationId), and matching
  // the stale one against conversations.value (already updated to the real id) would silently
  // find nothing to update, leaving the old title on screen until a reload re-fetches it fresh.
  const resolvedId = resolveConversationId(id)
  const conversation = conversations.value.find((item) => item.id === resolvedId)
  if (conversation) conversation.title = title // shown immediately, not held up by the request

  if (!confirmedConversationIds.has(resolvedId)) return // a local-only placeholder, nothing to persist yet
  try {
    await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
  } catch {
    // Best-effort: the rename already shows locally even if it failed to persist - a later
    // reload would just show the old title again, not worth a visible error for.
  }
}

async function deleteConversation(id: string) {
  const resolvedId = resolveConversationId(id)
  const wasConfirmed = confirmedConversationIds.has(resolvedId)
  const wasActive = activeId.value === resolvedId

  conversations.value = conversations.value.filter((item) => item.id !== resolvedId)
  delete messagesByConversation.value[resolvedId]
  loadedConversationIds.delete(resolvedId)
  confirmedConversationIds.delete(resolvedId)

  if (wasActive) {
    const next = conversations.value[0]
    if (next) selectConversation(next.id)
    else newConversation()
  }

  if (!wasConfirmed) return // a local-only placeholder was never a real backend conversation
  try {
    await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}`, { method: 'DELETE', credentials: 'include' })
  } catch {
    // Best-effort: already removed from the sidebar regardless - a stale row would only
    // reappear on the next full reload, not worth a visible error for.
  }
}

// One page loaded at a time - the sidebar list can grow into the hundreds for an active user,
// and fetching it all upfront (page_size=100+) would only get worse over time. `loadMoreConversations`
// (called by the sidebar as it scrolls near the bottom) fetches the next page instead.
let conversationsNextPage = 1
const conversationsTotal = ref(0)
const conversationsHasMore = ref(true)
const loadingMoreConversations = ref(false)

// Populates the sidebar with real past conversations on load, and - only if the app opened on
// "/" with nothing typed yet, never for a bookmarked /c/<id> already being restored - takes over
// the placeholder with the most recently active one instead of starting on an empty new chat.
async function initializeConversations() {
  try {
    const { items, total } = await fetchConversationsList(1)
    conversationsNextPage = 2
    conversationsTotal.value = total
    conversationsHasMore.value = items.length < total
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

async function loadMoreConversations() {
  if (loadingMoreConversations.value || !conversationsHasMore.value) return
  loadingMoreConversations.value = true
  try {
    const { items, total } = await fetchConversationsList(conversationsNextPage)
    conversationsNextPage += 1
    conversationsTotal.value = total

    const existingIds = new Set(conversations.value.map((item) => item.id))
    const newOnes = items.filter((item) => !existingIds.has(item.id))
    conversations.value.push(...newOnes.map((item) => ({ id: item.id, title: item.title || 'Nouvelle conversation' })))
    for (const item of items) confirmedConversationIds.add(item.id)

    conversationsHasMore.value = conversations.value.length < conversationsTotal.value
  } catch {
    // Best-effort - leave conversationsHasMore as-is, the next scroll-triggered call retries.
  } finally {
    loadingMoreConversations.value = false
  }
}

async function createRun(
  conversationId: string,
  query: string,
  collectionIds: string[],
  webSearchEnabled: boolean,
): Promise<RunOut> {
  // Only ever send a conversation_id the backend actually confirmed exists - the sidebar's
  // placeholder id would 404 (ConversationNotFoundError), so a brand-new conversation's first
  // run omits it and lets the backend create one instead.
  const known = confirmedConversationIds.has(conversationId) ? conversationId : undefined
  const response = await fetch(`${API_BASE_URL}/api/runs`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      conversation_id: known,
      collection_ids: collectionIds.length > 0 ? collectionIds : undefined,
      web_search_enabled: webSearchEnabled,
    }),
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

async function submitFeedback(runId: string, value: 'up' | 'down', details?: FeedbackDetails): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/feedback`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      value,
      reasons: details?.reasons ?? [],
      comment: details?.comment || null,
      validated_source_ids: details?.validatedSourceIds ?? [],
      added_sources: details?.addedSources.map((source) => ({ title: source.title, url: source.url })) ?? [],
    }),
  })
  if (!response.ok) throw new Error(`${response.status}`)
}

// The backend cites each claim with its evidence excerpt's raw id in brackets (e.g.
// "[f8109fc0-88cc-...]" - see generate_answer.py's system prompt), so the model's grounding
// stays verifiable server-side. Showing that literal uuid to the user is meaningless, though -
// this renumbers every distinct id into a short footnote ([1], [2], ...) in order of first
// appearance in the text, and builds the sources panel to match those same numbers.
function formatAnswerWithCitations(answer: string, citations: Citation[] | null | undefined): [string, Source[] | undefined] {
  if (!citations?.length) return [answer, undefined]

  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]))
  const footnoteNumberById = new Map<string, number>()
  const sources: Source[] = []

  // Only "search" and "page_content" ever point at a real, openable document page - every other
  // tool (list_collections, collection_summary, list_documents) is a knowledge-base-level lookup
  // with nothing to open a page for, just its own input/output. "web_search" is its own case
  // below: a real, openable link too, just external rather than a document page.
  const DOCUMENT_TOOLS = new Set(['search', 'page_content'])

  function footnoteFor(evidenceId: string): number | undefined {
    const citation = citationById.get(evidenceId)
    if (!citation) return undefined
    let footnoteNumber = footnoteNumberById.get(evidenceId)
    if (footnoteNumber === undefined) {
      footnoteNumber = sources.length + 1
      footnoteNumberById.set(evidenceId, footnoteNumber)
      const sourceTitle = citation.source ?? `Source ${citation.vdb_id}`
      const isWeb = citation.tool === 'web_search'
      const isDocument = !isWeb && !!citation.tool && DOCUMENT_TOOLS.has(citation.tool)
      let type: Source['type']
      if (isWeb) type = 'web'
      else if (citation.tool !== undefined) type = isDocument ? 'document' : 'tool'
      sources.push({
        title: `${footnoteNumber}. ${sourceTitle}`,
        id: citation.source_id ?? undefined,
        type,
        url: isWeb ? (citation.url ?? undefined) : undefined,
        collectionId: citation.vdb_id,
        documentId: isDocument ? (citation.document_id ?? undefined) : undefined,
        pageNumber: isDocument ? (citation.page_number ?? undefined) : undefined,
        query: citation.query,
        content: citation.content,
      })
    }
    return footnoteNumber
  }

  // Permissive on the outside (a small/local model sometimes cites several ids in one bracket,
  // separated by a comma/space/semicolon), strict on each individual id (an exact match against
  // a real citation) - an id that doesn't match anything is never shown raw, it's just dropped,
  // since an unverifiable citation is itself a grounding problem, not a display one.
  const content = answer
    .replace(/\[([0-9a-f][0-9a-f,;\s-]{6,}[0-9a-f])\]/gi, (_match, group: string) => {
      const numbers = [
        ...new Set(
          group
            .split(/[,;\s]+/)
            .map((candidate) => footnoteFor(candidate.trim()))
            .filter((n): n is number => n !== undefined),
        ),
      ]
      return numbers.length ? `[${numbers.join(',')}]` : ''
    })
    .replace(/ {2,}/g, ' ')
    .replace(/ ([.,;:!?])/g, '$1')

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
    return { id, role: 'assistant', content: activityLabel(run), runId: run.id, pending: true }
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

async function runQuery(
  conversationId: string,
  messageId: string,
  query: string,
  collectionIds: string[],
  webSearchEnabled: boolean,
) {
  try {
    const run = await createRun(conversationId, query, collectionIds, webSearchEnabled)
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

function sendMessage(content: string, collectionIds: string[] = [], webSearchEnabled = false) {
  const conversationId = activeId.value

  const pending = pendingClarifications[conversationId]
  if (pending) {
    delete pendingClarifications[conversationId]
    messagesByConversation.value[conversationId].push({ id: crypto.randomUUID(), role: 'user', content })
    replaceMessage(conversationId, pending.messageId, {
      id: pending.messageId,
      role: 'assistant',
      content: 'Recherche en cours',
      pending: true,
    })
    resumeAndTrack(conversationId, pending.runId, pending.messageId, content)
    return
  }

  const messageId = crypto.randomUUID()
  messagesByConversation.value[conversationId].push(
    { id: crypto.randomUUID(), role: 'user', content },
    { id: messageId, role: 'assistant', content: 'Recherche en cours', pending: true },
  )
  runQuery(conversationId, messageId, content, collectionIds, webSearchEnabled)
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
  list[index] = { id, role: 'assistant', content: 'Recherche en cours', pending: true }
  // Regenerating never re-enables web search on its own - it's not tracked per message, and
  // silently turning it back on for a rerun the user didn't explicitly opt into would violate
  // the same "off by default, opt-in per message" rule the composer toggle itself follows.
  runQuery(conversationId, id, lastUserMessage.content, [], false)
}

function sendFeedback(id: string, value: 'up' | 'down', details?: FeedbackDetails) {
  const runId = messages.value.find((message) => message.id === id)?.runId
  // No run means nothing was ever persisted for this message (shouldn't happen - the feedback
  // buttons only render on a completed assistant message, which always has one) - silently
  // drop rather than crash the UI over a feedback click.
  if (!runId) return
  submitFeedback(runId, value, details).catch((error) => {
    console.error('Failed to submit feedback', error)
  })
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
  executionErrorMessageIds.value.delete(id)
  const runId = messages.value.find((message) => message.id === id)?.runId
  if (!runId) {
    executionEventsByMessageId.value[id] = []
    return
  }
  if (executionEventsByMessageId.value[id] && !activePolls.has(id)) return
  try {
    const items = await fetchRunEvents(runId)
    executionEventsByMessageId.value[id] = items.map((item) => ({
      id: item.id,
      label: eventLabel(item.type),
      taskId: item.task_id ?? undefined,
      createdAt: item.created_at,
    }))
  } catch (error) {
    console.error(`Failed to fetch events for run ${runId}`, error)
    executionErrorMessageIds.value.add(id)
    executionEventsByMessageId.value[id] = []
  }
}

function closeExecutionDetails() {
  activeExecutionMessageId.value = undefined
}

export function useChat() {
  return {
    conversations,
    conversationsHasMore,
    loadingMoreConversations,
    loadMoreConversations,
    activeId,
    messages,
    activeSources,
    activeExecutionMessageId,
    activeExecutionEvents,
    activeExecutionError,
    selectConversation,
    newConversation,
    renameConversation,
    deleteConversation,
    sendMessage,
    regenerateMessage,
    sendFeedback,
    showSources,
    closeSources,
    showExecutionDetails,
    closeExecutionDetails,
  }
}
