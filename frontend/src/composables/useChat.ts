import { computed, ref } from 'vue'
import { router } from '../router'
import type { ChatMessage, Conversation, FeedbackDetails, Source } from '../types/chat'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

// Backend response shapes (snake_case) - see backend/app/schemas/run.py.
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

function resolveConversationId(id: string): string {
  let resolved = id
  while (conversationAliases[resolved]) resolved = conversationAliases[resolved]
  return resolved
}

function migrateConversationId(placeholderId: string, realId: string): string {
  confirmedConversationIds.add(realId)
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

// `navigate: false` is used when a route change already triggered this (see
// ChatView's route watcher) - pushing again there would just double the entry.
function selectConversation(id: string, options: { navigate?: boolean } = {}) {
  activeId.value = id
  const target = `/c/${id}`
  if (options.navigate !== false && router.currentRoute.value.fullPath !== target) {
    router.push(target)
  }
}

function newConversation() {
  const id = crypto.randomUUID()
  conversations.value.unshift({ id, title: 'Nouvelle conversation' })
  messagesByConversation.value[id] = []
  activeId.value = id
  router.push(`/c/${id}`)
}

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

function toSources(citations: RunOut['citations']): Source[] | undefined {
  if (!citations?.length) return undefined
  const seen = new Set<string>()
  const sources: Source[] = []
  for (const citation of citations) {
    const title = citation.source ?? `Source ${citation.vdb_id}`
    if (seen.has(title)) continue
    seen.add(title)
    sources.push({ title })
  }
  return sources
}

function assistantMessageFor(id: string, run: RunOut): ChatMessage {
  if (run.status === 'waiting_for_user') {
    return {
      id,
      role: 'assistant',
      content: run.pending_human_action?.question ?? 'Pouvez-vous préciser votre demande ?',
    }
  }
  if (!TERMINAL_STATUSES.has(run.status)) {
    return { id, role: 'assistant', content: run.current_activity ?? 'Recherche en cours…' }
  }
  if (run.status === 'completed') {
    return {
      id,
      role: 'assistant',
      content: run.answer || "Je n'ai pas trouvé de réponse dans vos collections.",
      sources: toSources(run.citations),
    }
  }
  return {
    id,
    role: 'assistant',
    content: run.status === 'cancelled' ? 'Cette recherche a été annulée.' : run.error || 'Cette recherche a échoué.',
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
  activeSourcesMessageId.value = id
}

function closeSources() {
  activeSourcesMessageId.value = undefined
}

export function useChat() {
  return {
    conversations,
    activeId,
    messages,
    activeSources,
    selectConversation,
    newConversation,
    sendMessage,
    regenerateMessage,
    sendFeedback,
    showSources,
    closeSources,
  }
}
