import { applyEvents, type LiveStep } from '../utils/runSteps'
import { computed, ref } from 'vue'
import { router } from '../router'
import { useAssistants } from './useAssistants'
import { useCollectionImports } from './useCollectionImports'
import type { QaSuggestion } from './useQaSuggestions'
import type {
  ChatMessage,
  Conversation,
  ConversationFile,
  DiscussionFeedback,
  DiscussionScore,
  CreationProposal,
  EditProposal,
  ExecutionEvent,
  FeedbackDetails,
  AssistantQuestion,
  QuestionAnswer,
  ToolCallRequest,
  GeneratedImage,
  Source,
} from '../types/chat'
import { answerHasNoSource } from '../utils/answerSources'
import { formatAnswers, toRequestAnswers } from '../utils/questionAnswers'
import { type AnswerDelta, applyDelta, isEndingStatus } from '../utils/runStream'
import { useImageGeneration } from './useImageGeneration'

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
  // The precise provenance of this excerpt (document, qa, summary, collection, web) - stamped
  // by each evidence producer in the worker's research_task.py and carried through
  // build_answer_context/generate_answer/link_citations. Absent on citations persisted before
  // this field existed - formatAnswerWithCitations falls back to inferring from `tool`.
  evidence_kind?: string
  // Whether the answer cites this excerpt or only consulted it (#402).
  cited?: boolean
  // The passage the citation rests on, as the excerpt has it, and where it is in `content` (#402).
  quote?: string | null
  quote_start?: number | null
  quote_end?: number | null
  document_id?: string | null
  chunk_id?: string | null
  page_number?: number | null
  // Only ever set on a web_search citation - a real, browsable external URL.
  url?: string | null
  query?: string
  content?: string
  // Where a cited question-answer pair comes from (#351) - only on a "qa" citation that has a passage.
  qa_source?: {
    document_id: string
    document_name: string
    page_number: number
    passage: string
    start?: number | null
    end?: number | null
  } | null
  // The backend Source row this citation was materialized into (see the backend's
  // SourceRepository.link_citations) - absent on a "tool" citation or one persisted before this
  // existed. See Source.id in types/chat.ts.
  source_id?: string | null
  // Set when the cited document is a living one (#171): the revision of it the answer was drawn from.
  document_revision?: number | null
  // Names from the root down to the cited collection (#220) - absent on older citations.
  vdb_path?: string[]
}

interface MessageOut {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  run_id: string | null
  citations: Citation[] | null
  edit_proposal: ProposalOut | null
  unexplored_collection_ids?: string[] | null
  questions?: QuestionOut[] | null
  questions_answer?: { selected: string[]; text: string | null }[] | null
  questions_abandoned?: boolean
  feedback: 'up' | 'down' | null
  assistant_name?: string | null
  tool_calls?: ToolCallOut[] | null
  images?: ImageOut[] | null
}

// Backend shape (snake_case) of an image made in the chat (#518).
interface ImageOut {
  id: string
  prompt: string
  model: string
  content_type: string
  width: number
  height: number
  size_bytes: number
}

function imageUrl(conversationId: string, imageId: string): string {
  return `${API_BASE_URL}/api/conversations/${conversationId}/images/${imageId}`
}

function toImages(conversationId: string, raw: ImageOut[] | null | undefined): GeneratedImage[] | undefined {
  return raw?.length
    ? raw.map((item) => ({
        id: item.id,
        prompt: item.prompt,
        model: item.model,
        contentType: item.content_type,
        width: item.width,
        height: item.height,
        sizeBytes: item.size_bytes,
        url: imageUrl(conversationId, item.id),
      }))
    : undefined
}

// Backend shape (snake_case) of a request to run a tool that changes data (#343).
interface ToolCallOut {
  id: string
  tool_name: string
  server_name: string | null
  arguments: Record<string, unknown>
  status: ToolCallRequest['status']
  result_code: string | null
}

function toToolCalls(raw: ToolCallOut[] | null | undefined): ToolCallRequest[] | undefined {
  return raw?.length
    ? raw.map((item) => ({
        id: item.id,
        toolName: item.tool_name,
        serverName: item.server_name,
        arguments: item.arguments,
        status: item.status,
        resultCode: item.result_code,
      }))
    : undefined
}

// Backend shape (snake_case) of the questions with options the assistant asked (#344).
interface QuestionOut {
  question: string
  header: string
  multi_select: boolean
  options: { label: string; description: string }[]
}

function toQuestions(raw: QuestionOut[] | null | undefined): AssistantQuestion[] | undefined {
  return raw?.length
    ? raw.map((item) => ({
        question: item.question,
        header: item.header,
        multiSelect: item.multi_select,
        options: item.options,
      }))
    : undefined
}

function toQuestionsAnswer(raw: MessageOut['questions_answer']): QuestionAnswer[] | undefined {
  return raw ? raw.map((item) => ({ selected: item.selected, text: item.text ?? '' })) : undefined
}

// Backend shape (snake_case) of Run.edit_proposal - see backend/app/models/run.py. Two kinds share
// the column: a change to an existing document (no `kind`), and a new Markdown document to create.
interface EditProposalOut {
  collection_id: string
  document_id: string
  document_name: string
}

interface CreationProposalOut {
  kind: 'create'
  status: CreationProposal['status']
  collection_id: string
  collection_name: string
  name: string
  content: string
  document_id?: string
}

type ProposalOut = EditProposalOut | CreationProposalOut

function isCreation(raw: ProposalOut | null | undefined): raw is CreationProposalOut {
  return !!raw && 'kind' in raw && raw.kind === 'create'
}

function toEditProposal(raw: ProposalOut | null | undefined): EditProposal | undefined {
  return raw && !isCreation(raw)
    ? { collectionId: raw.collection_id, documentId: raw.document_id, documentName: raw.document_name }
    : undefined
}

function toCreationProposal(raw: ProposalOut | null | undefined): CreationProposal | undefined {
  return isCreation(raw)
    ? {
        status: raw.status,
        collectionId: raw.collection_id,
        collectionName: raw.collection_name,
        name: raw.name,
        content: raw.content,
        documentId: raw.document_id,
      }
    : undefined
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
  // The part of the answer written so far, while the run is still generating it.
  partial_answer?: string | null
  citations: Citation[] | null
  edit_proposal: ProposalOut | null
  unexplored_collection_ids?: string[] | null
  questions?: QuestionOut[] | null
  tool_calls?: ToolCallOut[] | null
  images?: ImageOut[] | null
  assistant_name?: string | null
  assistant_inaccessible_collections?: number
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
// Which conversation ids already have their message history loaded (or definitively don't exist
// on the backend) - avoids re-fetching on every sidebar click, and lets a brand-new local-only
// conversation (newConversation()) skip a fetch that would just 404.
const loadedConversationIds = new Set<string>()

// Files attached directly to a conversation (§ conv-files, #88/#89/#90/#91) - the composer's
// paperclip button, not a collection's own document list. Keyed the same way as
// messagesByConversation (placeholder id until migrateConversationId renames it).
const attachedFilesByConversation = ref<Record<string, ConversationFile[]>>({})
const filePolls = new Map<string, ReturnType<typeof setInterval>>()
// A file attached before the conversation has a real backend id yet (e.g. the very first
// message of a brand-new chat) can't be uploaded - there's nothing to attach it to. Queued here
// instead, and flushed once migrateConversationId resolves a real id.
const queuedFileUploads = new Map<string, { tempId: string; file: File }[]>()

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
  attachedFilesByConversation.value[realId] = [
    ...(attachedFilesByConversation.value[realId] ?? []),
    ...(attachedFilesByConversation.value[currentId] ?? []),
  ]
  delete attachedFilesByConversation.value[currentId]
  conversationAliases[currentId] = realId

  const conversation = conversations.value.find((item) => item.id === currentId)
  if (conversation) conversation.id = realId
  if (activeId.value === currentId) {
    activeId.value = realId
    router.replace(`/c/${realId}`)
  }

  const queued = queuedFileUploads.get(currentId)
  if (queued) {
    queuedFileUploads.delete(currentId)
    for (const { tempId, file } of queued) uploadAttachedFile(realId, file, tempId)
  }
  // ZIPs dropped before the conversation existed backend-side (#223) - same flush.
  useCollectionImports().flushConversation(currentId, realId)
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
// backend/app/agent/graph/services/events.py) -> the French label shown as the chat
// placeholder while a run is in progress. Run.current_activity itself is worker-internal English
// (used for logging/debugging), never shown as-is except for "research_task", whose activity
// *is* the task's own query text - already meaningful on its own, in whatever language the user
// asked in.
const NODE_LABELS: Record<string, string> = {
  prepare: 'Démarrage de la recherche',
  plan: 'Analyse de votre question',
  answer_help: "Recherche de l'aide",
  edit_resolve: 'Préparation de la modification',
  edit_request: "Demande à l'agent d'édition",
  edit_wait: "Attente de l'agent d'édition",
  edit_report: 'Résumé de la modification',
  create_resolve: 'Préparation du document',
  create_write: 'Rédaction du document',
  merge_evidence: 'Fusion des résultats de recherche',
  gate: 'Vérification de la pertinence des résultats',
  widen_search: 'Recherche dans toutes vos bases de connaissances',
  build_answer_context: 'Préparation de la réponse',
  generate_answer: 'Génération de la réponse',
  // Runs made before the agent was reduced to one planning call keep their old steps.
  load_context: 'Démarrage de la recherche',
  load_accessible_vdbs: 'Vérification de vos bases de connaissances accessibles',
  analyze_query: 'Analyse de votre question',
  decompose_query: 'Découpage de votre question',
  build_research_plan: 'Planification de la recherche',
  evaluate_coverage: 'Vérification de la pertinence des résultats',
  clarify_coverage: 'En attente de votre précision',
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
// backend/app/agent/graph/services/events.py).
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
  search_widened: 'Recherche élargie à toutes les bases de connaissances',
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

async function fetchRunEvents(runId: string, since?: string): Promise<RunEventOut[]> {
  const query = since ? `?since=${encodeURIComponent(since)}` : ''
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/events${query}`, { credentials: 'include' })
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

async function fetchConversation(conversationId: string): Promise<ConversationOut> {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
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
        noSources: answerHasNoSource(item.citations, sources),
        runId: item.run_id ?? undefined,
        feedback: item.feedback ?? null,
        editProposal: toEditProposal(item.edit_proposal),
        creationProposal: toCreationProposal(item.edit_proposal),
        unexploredCollectionIds: item.unexplored_collection_ids ?? undefined,
        questions: toQuestions(item.questions),
        questionsAnswer: toQuestionsAnswer(item.questions_answer),
        questionsAbandoned: item.questions_abandoned ?? false,
        toolCalls: toToolCalls(item.tool_calls),
        images: toImages(conversationId, item.images),
        assistantName: item.assistant_name ?? undefined,
      }
    })
    confirmedConversationIds.add(conversationId)
    // ZIPs imported from this conversation (#223), with their attach suggestion if any.
    useCollectionImports().loadConversationImports(conversationId)
    // A running run's assistant message only exists in memory, not in DB (it's persisted
    // when the run completes via update_run_result). After a page refresh, the user message
    // is there but the assistant placeholder is gone - fetch active runs and resume polling
    // so the user sees the run finish instead of a dangling question with no answer.
    try {
      const activeRuns = await fetchActiveRuns(conversationId)
      for (const run of activeRuns) {
        const messageId = crypto.randomUUID()
        messagesByConversation.value[conversationId].push(assistantMessageFor(messageId, run))
        trackRun(conversationId, messageId, run)
      }
    } catch {
      // Best-effort - the messages are already loaded, active run recovery is a bonus.
    }
    refreshAttachedFiles(conversationId) // best-effort itself, see its own try/catch
  } catch {
    if (!messagesByConversation.value[conversationId]) messagesByConversation.value[conversationId] = []
  }
}

// --- Files attached directly to a conversation (§ conv-files, #88/#89/#90/#91/#92) ---

interface ConversationFilingCandidateOut {
  collection_id: string
  collection_name: string
  collection_description: string
  score: number
}

interface ConversationDocumentOut {
  id: string
  name: string
  status: ConversationFile['status']
  progress: number
  suggested_collection_id: string | null
  suggested_collection_name: string | null
  suggested_collection_score: number | null
  filing_candidates: ConversationFilingCandidateOut[] | null
  filing_dismissed: boolean
}

function toConversationFile(item: ConversationDocumentOut): ConversationFile {
  return {
    id: item.id,
    name: item.name,
    status: item.status,
    progress: item.progress,
    suggestedCollectionId: item.suggested_collection_id ?? undefined,
    suggestedCollectionName: item.suggested_collection_name ?? undefined,
    suggestedCollectionScore: item.suggested_collection_score ?? undefined,
    filingCandidates: (item.filing_candidates ?? []).map((candidate) => ({
      collectionId: candidate.collection_id,
      collectionName: candidate.collection_name,
      collectionDescription: candidate.collection_description,
      score: candidate.score,
    })),
    filingDismissed: item.filing_dismissed,
  }
}

async function fetchConversationFiles(conversationId: string): Promise<ConversationDocumentOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/documents`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  return response.json()
}

async function refreshAttachedFiles(conversationId: string) {
  const resolvedId = resolveConversationId(conversationId)
  if (!confirmedConversationIds.has(resolvedId)) return // local-only placeholder, nothing to fetch yet
  try {
    const items = await fetchConversationFiles(resolvedId)
    attachedFilesByConversation.value[resolvedId] = items.map(toConversationFile)
  } catch {
    // Best-effort, same pattern as refreshDiscussionScores - a stale chip list just means the
    // next poll tick (or conversation switch) picks up the real state.
  }
}

function pollAttachedFilesWhileProcessing(conversationId: string) {
  if (filePolls.has(conversationId)) return
  filePolls.set(
    conversationId,
    setInterval(async () => {
      await refreshAttachedFiles(conversationId)
      const stillProcessing = (attachedFilesByConversation.value[conversationId] ?? []).some(
        (file) => file.status === 'pending' || file.status === 'indexing',
      )
      if (!stillProcessing) {
        clearInterval(filePolls.get(conversationId))
        filePolls.delete(conversationId)
      }
    }, 2000),
  )
}

function replaceAttachedFile(conversationId: string, fileId: string, file: ConversationFile | null) {
  const list = attachedFilesByConversation.value[conversationId] ?? []
  const index = list.findIndex((item) => item.id === fileId)
  if (file === null) {
    if (index !== -1) list.splice(index, 1)
  } else if (index === -1) {
    list.push(file)
  } else {
    list[index] = file
  }
  attachedFilesByConversation.value[conversationId] = [...list]
}

// Actually uploads a file to a conversation that's known to have a real backend id - called
// either immediately (conversation already confirmed) or once migrateConversationId resolves one
// for a file attached before the first message was ever sent (see attachFile below).
async function uploadAttachedFile(conversationId: string, file: File, tempId: string) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/documents/file`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const created: ConversationDocumentOut = await response.json()
    replaceAttachedFile(conversationId, tempId, toConversationFile(created))
    pollAttachedFilesWhileProcessing(conversationId)
  } catch {
    replaceAttachedFile(conversationId, tempId, {
      id: tempId,
      name: file.name,
      status: 'error',
      progress: 0,
      filingCandidates: [],
      filingDismissed: false,
    })
  }
}

// Attaches a file to the active conversation from the composer's paperclip button - shown
// immediately as a chip (optimistic), queued rather than uploaded right away if this is a
// brand-new conversation with no backend id yet (see migrateConversationId's flush).
function attachFile(conversationId: string, file: File) {
  const resolvedId = resolveConversationId(conversationId)
  const tempId = crypto.randomUUID()
  replaceAttachedFile(resolvedId, tempId, {
    id: tempId,
    name: file.name,
    status: confirmedConversationIds.has(resolvedId) ? 'pending' : 'queued',
    progress: 0,
    filingCandidates: [],
    filingDismissed: false,
  })
  if (confirmedConversationIds.has(resolvedId)) {
    uploadAttachedFile(resolvedId, file, tempId)
  } else {
    const queued = queuedFileUploads.get(resolvedId) ?? []
    queued.push({ tempId, file })
    queuedFileUploads.set(resolvedId, queued)
  }
}

// A ZIP dropped into the composer becomes a collection of its own (#223), not a conversation
// file - followed by useCollectionImports, queued like attachFile until the conversation exists.
function attachZip(conversationId: string, file: File) {
  const resolvedId = resolveConversationId(conversationId)
  useCollectionImports().importIntoConversation(resolvedId, file, confirmedConversationIds.has(resolvedId))
}

const activeImports = computed(() => {
  const { imports, importIdsByConversation } = useCollectionImports()
  return (importIdsByConversation.value[resolveConversationId(activeId.value)] ?? [])
    .map((id) => imports.value[id])
    .filter((item) => item !== undefined)
})

async function removeAttachedFile(conversationId: string, fileId: string) {
  const resolvedId = resolveConversationId(conversationId)
  const file = (attachedFilesByConversation.value[resolvedId] ?? []).find((item) => item.id === fileId)
  replaceAttachedFile(resolvedId, fileId, null)
  if (file?.status === 'queued') {
    const queued = queuedFileUploads.get(resolvedId)
    if (queued) queuedFileUploads.set(resolvedId, queued.filter((item) => item.tempId !== fileId))
    return // never reached the backend, nothing to delete there
  }
  try {
    await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}/documents/${fileId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
  } catch {
    // Best-effort: already removed from the composer regardless - a stale server-side row isn't
    // visible anywhere the user would notice, same tradeoff as deleteConversation.
  }
}

const activeAttachedFiles = computed(() => attachedFilesByConversation.value[resolveConversationId(activeId.value)] ?? [])

// Local-only updates for the chat's file-filing modal (§122) - the actual API call goes through
// useFiling().decideFiling, shared with the "Fichiers à ranger" review page; these two just keep
// the composer's chips in sync with its result, without a second network round-trip.
function markAttachedFileDismissed(conversationId: string, fileId: string) {
  const resolvedId = resolveConversationId(conversationId)
  const file = (attachedFilesByConversation.value[resolvedId] ?? []).find((item) => item.id === fileId)
  if (file) replaceAttachedFile(resolvedId, fileId, { ...file, filingDismissed: true })
}

function dropAttachedFileLocally(conversationId: string, fileId: string) {
  replaceAttachedFile(resolveConversationId(conversationId), fileId, null)
}

// `navigate: false` is used when a route change already triggered this (see
// ChatView's route watcher) - pushing again there would just double the entry.
// The message a search result led to (#509): the chat scrolls to it once the conversation is loaded, then forgets it.
const focusedMessageId = ref<string | null>(null)

function selectConversation(id: string, options: { navigate?: boolean; messageId?: string } = {}) {
  activeId.value = id
  focusedMessageId.value = options.messageId ?? null
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

// Animates a conversation title character-by-character (ChatGPT-style "streaming" reveal).
// Clears any previous animation still running on the same conversation so a rapid second rename
// doesn't fight the first. The interval is stored in a module-level Map keyed by conversation id.
const titleAnimationInterval = new Map<string, ReturnType<typeof setInterval>>()

function animateTitle(conversation: Conversation, finalTitle: string) {
  const previous = titleAnimationInterval.get(conversation.id)
  if (previous) clearInterval(previous)

  // If the title is already the target (or empty), no animation needed.
  if (!finalTitle || conversation.title === finalTitle) {
    conversation.title = finalTitle
    return
  }

  // Start from the common prefix length so we don't "untype" characters that are already correct.
  let i = 0
  while (i < conversation.title.length && i < finalTitle.length && conversation.title[i] === finalTitle[i]) {
    i++
  }
  // If the current title is longer than the final one, reset to the prefix to avoid leftover chars.
  if (i < conversation.title.length) conversation.title = finalTitle.slice(0, i)

  const step = () => {
    if (i >= finalTitle.length) {
      const interval = titleAnimationInterval.get(conversation.id)
      if (interval) {
        clearInterval(interval)
        titleAnimationInterval.delete(conversation.id)
      }
      return
    }
    conversation.title = finalTitle.slice(0, i + 1)
    i++
  }

  // Reveal at ~30 chars/sec (one char every ~33ms) — fast enough for short titles, visible
  // enough to feel like a stream.
  const interval = setInterval(step, 33)
  titleAnimationInterval.set(conversation.id, interval)
}

async function renameConversation(id: string, title: string) {
  // Same resolution as deleteConversation - a sidebar row's id can be a pre-migration
  // placeholder still aliased to the real backend id (see migrateConversationId), and matching
  // the stale one against conversations.value (already updated to the real id) would silently
  // find nothing to update, leaving the old title on screen until a reload re-fetches it fresh.
  const resolvedId = resolveConversationId(id)
  const conversation = conversations.value.find((item) => item.id === resolvedId)
  if (conversation) animateTitle(conversation, title) // streaming reveal, not held up by the request

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

    // window.location.pathname, not router.currentRoute.value.path: this runs at module load
    // time, before Vue Router's own async initial navigation has necessarily resolved (no
    // `router.isReady()` await in main.ts) - currentRoute could still read its default '/' even
    // when the real URL is e.g. /tasks. Without this check at all, a hard reload/direct visit to
    // any non-chat route got silently hijacked back to the most recent conversation - activeId
    // starts as 'default' regardless of which route the page actually loaded on.
    if (
      activeId.value === 'default' &&
      (messagesByConversation.value.default ?? []).length === 0 &&
      window.location.pathname === '/'
    ) {
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

// What, beyond the query, a message asks of its run: whether attached collections bring their
// sub-collections along (#220), and whether it resumes the previous answer's exploration (#219).
interface RunOptions {
  includeDescendants?: boolean
  continueExploration?: boolean
  // The message answers the questions this run asked (#344), with the answer to each.
  answers?: { runId: string; answers: QuestionAnswer[] }
}

async function createRun(
  conversationId: string,
  query: string,
  collectionIds: string[],
  webSearchEnabled: boolean,
  options: RunOptions = {},
): Promise<RunOut> {
  // Only ever send a conversation_id the backend actually confirmed exists - the sidebar's
  // placeholder id would 404 (ConversationNotFoundError), so a brand-new conversation's first
  // run omits it and lets the backend create one instead.
  const known = confirmedConversationIds.has(conversationId) ? conversationId : undefined
  // The assistant picked in the chat (#514): the server uses its collections instead of the ones picked by hand, and adds
  // its instructions. An assistant that was removed since is answered with a 404 and the choice is dropped.
  const { selectedAssistantId } = useAssistants()
  const response = await fetch(`${API_BASE_URL}/api/runs`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      conversation_id: known,
      assistant_id: selectedAssistantId.value ?? undefined,
      collection_ids: collectionIds.length > 0 && !selectedAssistantId.value ? collectionIds : undefined,
      web_search_enabled: webSearchEnabled,
      include_descendants: options.includeDescendants ?? true,
      continue_exploration: options.continueExploration ?? false,
      answers_run_id: options.answers?.runId,
      answers: options.answers ? toRequestAnswers(options.answers.answers) : undefined,
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

async function fetchActiveRuns(conversationId: string): Promise<RunOut[]> {
  const response = await fetch(`${API_BASE_URL}/api/conversations/${conversationId}/active-runs`, {
    credentials: 'include',
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

async function fetchFeedback(runId: string): Promise<FeedbackDetails | null> {
  const response = await fetch(`${API_BASE_URL}/api/runs/${runId}/feedback`, { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status}`)
  const data = await response.json()
  if (!data) return null
  return {
    reasons: data.reasons ?? [],
    comment: data.comment ?? '',
    validatedSourceIds: data.validated_source_ids ?? [],
    addedSources: data.added_source_ids ?? [],
  }
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
      const isWeb = citation.evidence_kind === 'web' || citation.tool === 'web_search'
      const isDocument =
        citation.evidence_kind === 'document' ||
        (!isWeb && !!citation.tool && DOCUMENT_TOOLS.has(citation.tool))
      let type: Source['type']
      if (isWeb) type = 'web'
      else if (citation.evidence_kind === 'qa') type = 'qa'
      else if (citation.evidence_kind === 'summary') type = 'document_summary'
      else if (citation.evidence_kind === 'collection') type = 'collection'
      else if (citation.tool !== undefined) type = isDocument ? 'document' : 'tool'
      else type = 'tool'
      sources.push({
        title: `${footnoteNumber}. ${sourceTitle}`,
        id: citation.source_id ?? undefined,
        type,
        url: isWeb ? (citation.url ?? undefined) : undefined,
        collectionId: citation.vdb_id,
        collectionPath: citation.vdb_path?.length ? citation.vdb_path : undefined,
        documentId: isDocument ? (citation.document_id ?? undefined) : undefined,
        chunkId: isDocument ? (citation.chunk_id ?? undefined) : undefined,
        pageNumber: isDocument ? (citation.page_number ?? undefined) : undefined,
        revision: isDocument ? (citation.document_revision ?? undefined) : undefined,
        query: citation.query,
        content: citation.content,
        quote: citation.quote ?? undefined,
        qaSource: citation.qa_source
          ? {
              documentId: citation.qa_source.document_id,
              documentName: citation.qa_source.document_name,
              pageNumber: citation.qa_source.page_number,
              passage: citation.qa_source.passage,
              start: citation.qa_source.start ?? undefined,
              end: citation.qa_source.end ?? undefined,
            }
          : undefined,
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

  // The sources the answer cites without writing a marker (#402): the backend flags them, from the sources the model
  // listed. They are shown all the same, after the ones the text numbers.
  for (const citation of citations) if (citation.cited) footnoteFor(citation.evidence_id)

  return [content, sources.length ? sources : undefined]
}

// The agent cites with the ids of its evidence, e.g. "[abc123]" - numbered footnotes are only built once the
// run is complete, so while the answer is still coming the markers (and a half-written one) are left out.
function withoutCitationMarkers(text: string): string {
  return text.replace(/\s?\[[^\]\s]+\]/g, '').replace(/\s?\[[^\]\s]*$/, '')
}

// The steps of the runs going on, by the message they will answer: what the pending message shows, line by line, while
// the run goes (the execution panel lists the same events once it is over).
const liveStepsByMessageId = ref<Record<string, LiveStep[]>>({})
const lastEventByMessageId = new Map<string, string>()

// Reads what the run did since the last look. Best-effort: a missed look only means the steps show up a little later.
async function refreshLiveSteps(runId: string, messageId: string) {
  try {
    const items = await fetchRunEvents(runId, lastEventByMessageId.get(messageId))
    if (!items.length) return
    lastEventByMessageId.set(messageId, items[items.length - 1].id)
    liveStepsByMessageId.value[messageId] = applyEvents(
      liveStepsByMessageId.value[messageId] ?? [],
      items.map((item) => ({ id: item.id, type: item.type, taskId: item.task_id, data: item.data, createdAt: item.created_at })),
    )
  } catch {
    // The next look tries again.
  }
}

function forgetLiveSteps(messageId: string) {
  delete liveStepsByMessageId.value[messageId]
  lastEventByMessageId.delete(messageId)
}

function assistantMessageFor(id: string, run: RunOut): ChatMessage {
  // A run that was already waiting for an answer when questions stopped holding a run up (#344): it
  // can no longer be resumed, the question is shown and a new message goes on from there.
  if (run.status === 'waiting_for_user') {
    return {
      id,
      role: 'assistant',
      content: run.pending_human_action?.question ?? 'Pouvez-vous préciser votre demande ?',
      runId: run.id,
    }
  }
  if (!TERMINAL_STATUSES.has(run.status)) {
    // The answer is being written: show what exists so far instead of the step label.
    const partial = withoutCitationMarkers(run.partial_answer ?? '')
    const steps = liveStepsByMessageId.value[id]
    if (partial) return { id, role: 'assistant', content: partial, runId: run.id, pending: true, streaming: true, steps }
    return { id, role: 'assistant', content: activityLabel(run), runId: run.id, pending: true, steps }
  }
  if (run.status === 'completed') {
    const [content, sources] = formatAnswerWithCitations(
      run.answer || "Je n'ai pas trouvé de réponse dans vos collections.",
      run.citations,
    )
    return {
      id,
      role: 'assistant',
      content,
      sources,
      noSources: answerHasNoSource(run.citations, sources),
      runId: run.id,
      editProposal: toEditProposal(run.edit_proposal),
      creationProposal: toCreationProposal(run.edit_proposal),
      unexploredCollectionIds: run.unexplored_collection_ids ?? undefined,
      questions: toQuestions(run.questions),
      toolCalls: toToolCalls(run.tool_calls),
      // The images the assistant made while answering (#518): the run's own conversation, not a placeholder's.
      images: run.conversation_id ? toImages(run.conversation_id, run.images) : undefined,
      assistantName: run.assistant_name ?? undefined,
    }
  }
  return {
    id,
    role: 'assistant',
    content: run.status === 'cancelled' ? 'Cette recherche a été annulée.' : 'Cette recherche a échoué. Veuillez réessayer.',
    runId: run.id,
    error: run.status !== 'cancelled',
  }
}

function replaceMessage(conversationId: string, messageId: string, message: ChatMessage) {
  const list = messagesByConversation.value[resolveConversationId(conversationId)]
  const index = list?.findIndex((item) => item.id === messageId)
  if (index !== undefined && index !== -1) list[index] = message
}

// Applies a run's latest state to its placeholder message, and returns whether polling should
// stop - either a terminal status, or waiting_for_user (a run that was already waiting before #344):
// nothing will change there.
function applyRunUpdate(conversationId: string, messageId: string, run: RunOut): boolean {
  replaceMessage(conversationId, messageId, assistantMessageFor(messageId, run))
  if (run.status === 'waiting_for_user') return true
  const terminal = TERMINAL_STATUSES.has(run.status)
  // When the run completes, the worker generates a conversation title *after* marking the run
  // as completed (see agent_service._finalize) - so the title isn't available in this very
  // response. Poll the conversation once after a short delay to pick it up and animate it in.
  if (terminal && run.status === 'completed' && run.conversation_id) {
    const resolvedId = resolveConversationId(conversationId)
    setTimeout(async () => {
      try {
        const updated = await fetchConversation(resolvedId)
        const conversation = conversations.value.find((item) => item.id === resolvedId)
        if (conversation && updated.title && conversation.title !== updated.title) {
          animateTitle(conversation, updated.title)
        }
      } catch {
        // Best-effort - the title will show up on next page load.
      }
    }, 2000)
  }
  return terminal
}

// Follows a run until it ends, updating the placeholder assistant message in place: live when the stream of the run
// can be read (#510), by polling the run when it cannot.
function trackRun(conversationId: string, messageId: string, run: RunOut) {
  if (applyRunUpdate(conversationId, messageId, run)) return
  if (followRun(conversationId, messageId, run)) return
  pollRun(conversationId, messageId, run)
}

// --- The live stream of a run (#510) ---

// The steps and the words of the answer come as the agent produces them, over Server-Sent Events: no request per
// look, and the answer writes itself word by word instead of in half-second steps. The run itself (GET /runs/{id})
// stays the source of truth: the stream only shows, and the final answer is read from the run once it is over. Any
// trouble with the stream - a proxy that cuts it, a pod that is gone, a browser without EventSource - hands the run
// to the polling below, so the chat never depends on the stream.
const activeStreams = new Map<string, EventSource>()
// A line comes at least this often (a ping when nothing else): a stream silent for longer than this is dead.
const STREAM_SILENCE_MS = 45_000
const STREAM_MAX_ERRORS = 3

function streamDisabled(): boolean {
  return typeof EventSource === 'undefined' || import.meta.env.VITE_DISABLE_RUN_STREAM === 'true'
}

function followRun(conversationId: string, messageId: string, run: RunOut): boolean {
  if (streamDisabled()) return false
  let source: EventSource
  try {
    source = new EventSource(`${API_BASE_URL}/api/runs/${run.id}/stream`, { withCredentials: true })
  } catch {
    return false
  }
  activeStreams.set(messageId, source)

  let current = run
  let text = ''
  const seenSteps = new Set<string>()
  let watchdog: ReturnType<typeof setTimeout> | undefined
  // Connection errors in a row, with nothing received in between.
  let errors = 0

  const stop = () => {
    clearTimeout(watchdog)
    source.close()
    if (activeStreams.get(messageId) === source) activeStreams.delete(messageId)
  }
  // The stream failed: the polling takes over from where the run is.
  const giveUp = () => {
    stop()
    pollRun(conversationId, messageId, current)
  }
  const alive = () => {
    errors = 0
    clearTimeout(watchdog)
    watchdog = setTimeout(giveUp, STREAM_SILENCE_MS)
  }
  const show = () => {
    replaceMessage(
      conversationId,
      messageId,
      assistantMessageFor(messageId, { ...current, status: 'running', partial_answer: text || current.partial_answer }),
    )
  }
  const finish = async () => {
    stop()
    try {
      const final = await fetchRun(run.id)
      if (applyRunUpdate(conversationId, messageId, final)) {
        forgetLiveSteps(messageId)
        return
      }
      current = final
      pollRun(conversationId, messageId, final)
    } catch {
      pollRun(conversationId, messageId, current)
    }
  }
  const data = (event: Event) => JSON.parse((event as MessageEvent<string>).data)

  source.addEventListener('step', (event) => {
    alive()
    const item: RunEventOut = data(event)
    if (seenSteps.has(item.id)) return
    seenSteps.add(item.id)
    liveStepsByMessageId.value[messageId] = applyEvents(liveStepsByMessageId.value[messageId] ?? [], [
      { id: item.id, type: item.type, taskId: item.task_id, data: item.data, createdAt: item.created_at },
    ])
    lastEventByMessageId.set(messageId, item.id)
    show()
  })
  source.addEventListener('delta', (event) => {
    alive()
    const piece: AnswerDelta = data(event)
    text = applyDelta(text, piece)
    show()
  })
  source.addEventListener('status', (event) => {
    alive()
    const next: { status: string; current_node?: string | null; current_activity?: string | null } = data(event)
    if (isEndingStatus(next.status)) {
      void finish()
      return
    }
    current = { ...current, status: next.status, current_node: next.current_node ?? null, current_activity: next.current_activity ?? null }
    show()
  })
  source.addEventListener('ping', alive)
  source.addEventListener('unavailable', giveUp)
  // A cut connection is retried by the browser on its own, from the last event received. A stream the server refused
  // (not signed in, run not found, too many streams open) is closed for good, and one that keeps failing to connect is
  // not worth more tries: the polling does the same job.
  source.onerror = () => {
    errors += 1
    if (source.readyState === EventSource.CLOSED || errors >= STREAM_MAX_ERRORS) giveUp()
  }
  alive()
  return true
}

// Polls a run until it reaches a terminal status - the way a run is followed when its stream cannot be: same
// setInterval-based polling convention as useCollections.ts's pollDocumentsWhileProcessing.
function pollRun(conversationId: string, messageId: string, run: RunOut) {
  void refreshLiveSteps(run.id, messageId)
  const interval = setInterval(async () => {
    try {
      // The steps first, so that the message built from the run carries them.
      await refreshLiveSteps(run.id, messageId)
      const current = await fetchRun(run.id)
      if (applyRunUpdate(conversationId, messageId, current)) {
        clearInterval(interval)
        activePolls.delete(messageId)
        forgetLiveSteps(messageId)
      }
    } catch {
      clearInterval(interval)
      activePolls.delete(messageId)
      forgetLiveSteps(messageId)
      replaceMessage(conversationId, messageId, {
        id: messageId,
        role: 'assistant',
        content: 'Impossible de récupérer le résultat de cette recherche. Veuillez réessayer.',
        error: true,
      })
    }
  }, 700)
  activePolls.set(messageId, interval)
}

// Stops following the run of a message, however it is followed.
function stopTracking(messageId: string) {
  const interval = activePolls.get(messageId)
  if (interval) {
    clearInterval(interval)
    activePolls.delete(messageId)
  }
  const stream = activeStreams.get(messageId)
  if (stream) {
    stream.close()
    activeStreams.delete(messageId)
  }
}

async function runQuery(
  conversationId: string,
  messageId: string,
  query: string,
  collectionIds: string[],
  webSearchEnabled: boolean,
  options: RunOptions = {},
) {
  try {
    const run = await createRun(conversationId, query, collectionIds, webSearchEnabled, options)
    const resolvedId = run.conversation_id ? migrateConversationId(conversationId, run.conversation_id) : conversationId
    trackRun(resolvedId, messageId, run)
  } catch (failure) {
    const status = (failure as Error).message
    const { selectedAssistantId, select, refreshAssistants } = useAssistants()
    let content = 'Impossible de lancer cette recherche. Veuillez réessayer.'
    if (selectedAssistantId.value && status === '404') {
      // Removed, or no longer shared with this person: the chat goes back to no assistant, said plainly.
      select(null)
      refreshAssistants()
      content = "Cet assistant n'existe plus ou ne vous est plus partagé : le chat est revenu sans assistant. Posez à nouveau votre question."
    } else if (selectedAssistantId.value && status === '409') {
      content = "Vous ne pouvez lire aucune des collections de cet assistant, il n'a donc rien où chercher. Demandez à son auteur de vous les partager."
    }
    replaceMessage(conversationId, messageId, { id: messageId, role: 'assistant', content, error: true })
  }
}

function sendMessage(
  content: string,
  collectionIds: string[] = [],
  webSearchEnabled = false,
  includeDescendants = true,
  continueExploration = false,
) {
  const conversationId = activeId.value

  abandonOpenQuestions(conversationId)

  const messageId = crypto.randomUUID()
  messagesByConversation.value[conversationId].push(
    { id: crypto.randomUUID(), role: 'user', content },
    { id: messageId, role: 'assistant', content: 'Recherche en cours', pending: true },
  )
  runQuery(conversationId, messageId, content, collectionIds, webSearchEnabled, {
    includeDescendants,
    continueExploration,
  })
}

// An image asked for in the chat (#518), on the person's explicit request - never started by the model. The
// backend makes it, keeps it with the conversation and answers with both messages: nothing to poll, but a few
// seconds to wait, which the pending message says. A refusal (quota, policy, provider) is shown as the answer.
async function generateImage(prompt: string) {
  const conversationId = activeId.value
  abandonOpenQuestions(conversationId)
  const messageId = crypto.randomUUID()
  messagesByConversation.value[conversationId].push(
    { id: crypto.randomUUID(), role: 'user', content: prompt },
    { id: messageId, role: 'assistant', content: 'Génération de l’image en cours', pending: true },
  )
  try {
    const response = await fetch(`${API_BASE_URL}/api/images/generations`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        conversation_id: confirmedConversationIds.has(conversationId) ? conversationId : undefined,
      }),
    })
    if (!response.ok) throw new Error(await imageErrorMessage(response))
    const made: {
      conversation_id: string
      message: { id: string; content: string; images: ImageOut[] }
    } = await response.json()
    const resolvedId = migrateConversationId(conversationId, made.conversation_id)
    replaceMessage(resolvedId, messageId, {
      id: made.message.id,
      role: 'assistant',
      content: made.message.content,
      images: toImages(resolvedId, made.message.images),
    })
  } catch (error) {
    replaceMessage(conversationId, messageId, {
      id: messageId,
      role: 'assistant',
      content: error instanceof Error && error.message ? error.message : 'Impossible de générer l’image. Veuillez réessayer.',
      error: true,
    })
  }
  useImageGeneration().loadImageStatus()
}

// What the API says when it refuses a generation, in words for the person: its own message (a code and a sentence
// that show nothing of the provider), or a general one when there is none.
async function imageErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
  } catch {
    // No body to read.
  }
  return 'Impossible de générer l’image. Veuillez réessayer.'
}

// A starter question of the empty chat (#126): the backend puts the pair's stored answer and source
// into the conversation - no agent run, so nothing to wait for or poll - and it is then shown like
// any other completed answer.
async function askSuggestion(suggestion: QaSuggestion) {
  const conversationId = activeId.value
  const messageId = crypto.randomUUID()
  messagesByConversation.value[conversationId].push(
    { id: crypto.randomUUID(), role: 'user', content: suggestion.question },
    { id: messageId, role: 'assistant', content: 'Recherche en cours', pending: true },
  )
  try {
    const response = await fetch(`${API_BASE_URL}/api/qa-suggestions/${suggestion.id}/answer`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: confirmedConversationIds.has(conversationId) ? conversationId : undefined,
      }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const answer: { conversation_id: string; run_id: string } = await response.json()
    const resolvedId = migrateConversationId(conversationId, answer.conversation_id)
    trackRun(resolvedId, messageId, await fetchRun(answer.run_id))
  } catch {
    replaceMessage(conversationId, messageId, {
      id: messageId,
      role: 'assistant',
      content: 'Impossible de répondre à cette question. Veuillez réessayer.',
      error: true,
    })
  }
}

// Writing anything but an answer after the assistant's questions lets them go (#344): the card says so
// at once, as the backend will when the thread is read again.
function abandonOpenQuestions(conversationId: string) {
  for (const message of messagesByConversation.value[conversationId] ?? []) {
    if (message.questions?.length && message.questionsAnswer === undefined) message.questionsAbandoned = true
  }
}

// The user answers the questions a message asks (#344): their answer is a message of the thread, and a new
// run reads it with the conversation - nothing waited for it, whenever it comes.
async function answerQuestions(messageId: string, answers: QuestionAnswer[]) {
  const conversationId = activeId.value
  const list = messagesByConversation.value[conversationId]
  const asked = list?.find((message) => message.id === messageId)
  if (!asked?.questions || !asked.runId) return

  const content = formatAnswers(asked.questions, answers)
  asked.questionsAnswer = answers
  const placeholderId = crypto.randomUUID()
  list.push(
    { id: crypto.randomUUID(), role: 'user', content },
    { id: placeholderId, role: 'assistant', content: 'Recherche en cours', pending: true },
  )
  await runQuery(conversationId, placeholderId, content, [], false, { answers: { runId: asked.runId, answers } })
}

// The person authorises or refuses, together, the tools that change data which a message asked to run (#343). The
// backend runs what is authorised and writes the outcome as a message of the conversation, so the thread is read
// again to show it. Returns false when the answer could not be taken (already decided elsewhere, expired, offline).
async function decideToolCalls(messageId: string, approve: boolean): Promise<boolean> {
  const conversationId = activeId.value
  const asked = messagesByConversation.value[conversationId]?.find((message) => message.id === messageId)
  if (!asked?.toolCalls?.length || !asked.runId) return false
  let decided = false
  try {
    const response = await fetch(`${API_BASE_URL}/api/runs/${asked.runId}/tool-calls/decision`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve }),
    })
    decided = response.ok
    if (decided) asked.toolCalls = toToolCalls((await response.json()) as ToolCallOut[])
  } catch {
    return false
  }
  // A 409 means the request was decided in another tab or has expired: the thread tells the current state.
  try {
    const items = await fetchMessagesList(conversationId)
    const current = items.find((item) => item.run_id === asked.runId && item.role === 'assistant')
    if (current) asked.toolCalls = toToolCalls(current.tool_calls) ?? asked.toolCalls
    // What was authorised or refused is told by the message the backend wrote last.
    const outcome = items[items.length - 1]
    if (decided && outcome?.role === 'assistant' && outcome.run_id !== asked.runId) {
      messagesByConversation.value[conversationId].push({ id: outcome.id, role: 'assistant', content: outcome.content })
    }
  } catch {
    // The decision is taken; the outcome shows at the next visit of the conversation.
  }
  return decided
}

// "Go further" on the latest answer (#219): a new message resuming the exploration where that
// answer stopped - the backend hands the agent that answer's unexplored collections. The text is
// what the user sees in the thread; the agent reads it against the conversation's history.
function goFurther() {
  sendMessage('Va plus loin dans les sous-collections non explorées.', [], false, true, true)
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

  stopTracking(id)
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
  if (executionEventsByMessageId.value[id] && !activePolls.has(id) && !activeStreams.has(id)) return
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

// --- Discussion scoring (worker/evaluation → score_discussion task) ---

// Backend response shape (snake_case) - see backend/app/schemas/discussion_score.py.
interface DiscussionScoreOut {
  id: string
  conversation_id: string
  created_at: string
  message_count: number
  llm_model: string
  coherent: boolean
  coherence_issues: string[]
  context_usage_score: number
  context_usage_issues: string[]
  reasoning: string | null
}

// Discussion scores per conversation, loaded on demand (like messages).
const discussionScoresByConversation = ref<Record<string, DiscussionScore[]>>({})
const discussionScorePolls = new Map<string, ReturnType<typeof setInterval>>()

async function refreshDiscussionScores(conversationId: string) {
  const resolvedId = resolveConversationId(conversationId)
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}/discussion-scores`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const scores: DiscussionScoreOut[] = await response.json()
    discussionScoresByConversation.value[resolvedId] = scores.map((score) => ({
      id: score.id,
      conversationId: score.conversation_id,
      createdAt: score.created_at,
      messageCount: score.message_count,
      llmModel: score.llm_model,
      coherent: score.coherent,
      coherenceIssues: score.coherence_issues,
      contextUsageScore: score.context_usage_score,
      contextUsageIssues: score.context_usage_issues,
      reasoning: score.reasoning,
    }))
  } catch {
    // Ignored: same pattern as refreshEvaluation in useCollections.
  }
}

async function triggerDiscussionScore(conversationId: string) {
  const resolvedId = resolveConversationId(conversationId)
  if (!confirmedConversationIds.has(resolvedId)) return // local-only placeholder, nothing to score
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}/discussion-score`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) return
  } catch {
    return
  }
  // The worker runs asynchronously (Celery queue "evaluation"); poll until a
  // new score appears, mirroring pollEvaluationWhileRunning in useCollections.
  const previousCount = discussionScoresByConversation.value[resolvedId]?.length ?? 0
  let attempts = 0
  const maxAttempts = 150 // 5 min at 2s intervals
  if (discussionScorePolls.has(resolvedId)) return
  discussionScorePolls.set(
    resolvedId,
    setInterval(async () => {
      attempts++
      await refreshDiscussionScores(resolvedId)
      const currentCount = discussionScoresByConversation.value[resolvedId]?.length ?? 0
      if (currentCount > previousCount || attempts >= maxAttempts) {
        const handle = discussionScorePolls.get(resolvedId)
        if (handle) {
          clearInterval(handle)
          discussionScorePolls.delete(resolvedId)
        }
      }
    }, 2000),
  )
}

const activeDiscussionScores = computed(
  () => discussionScoresByConversation.value[resolveConversationId(activeId.value)] ?? [],
)

// --- Human discussion feedback (the manual counterpart to the LLM-generated score) ---

// Backend response shape (snake_case) - see backend/app/schemas/discussion_feedback.py.
interface DiscussionFeedbackOut {
  id: string
  conversation_id: string
  user_id: string
  rating: number
  coherent: boolean
  context_usage_score: number | null
  comment: string | null
  created_at: string
  updated_at: string
}

const discussionFeedbackByConversation = ref<Record<string, DiscussionFeedback[]>>({})

async function refreshDiscussionFeedback(conversationId: string) {
  const resolvedId = resolveConversationId(conversationId)
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}/discussion-feedback`, {
      credentials: 'include',
    })
    if (!response.ok) return
    const items: DiscussionFeedbackOut[] = await response.json()
    discussionFeedbackByConversation.value[resolvedId] = items.map((fb) => ({
      id: fb.id,
      conversationId: fb.conversation_id,
      userId: fb.user_id,
      rating: fb.rating,
      coherent: fb.coherent,
      contextUsageScore: fb.context_usage_score,
      comment: fb.comment,
      createdAt: fb.created_at,
      updatedAt: fb.updated_at,
    }))
  } catch {
    // Ignored: same pattern as refreshDiscussionScores.
  }
}

async function submitDiscussionFeedback(
  conversationId: string,
  data: { rating: number; coherent: boolean; contextUsageScore?: number | null; comment?: string | null },
) {
  const resolvedId = resolveConversationId(conversationId)
  if (!confirmedConversationIds.has(resolvedId)) return
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/${resolvedId}/discussion-feedback`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!response.ok) return
    await refreshDiscussionFeedback(resolvedId)
  } catch {
    // Ignored.
  }
}

const activeDiscussionFeedback = computed(
  () => discussionFeedbackByConversation.value[resolveConversationId(activeId.value)] ?? [],
)

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
    focusedMessageId,
    newConversation,
    renameConversation,
    deleteConversation,
    sendMessage,
    // Whether the backend knows this conversation yet: what its tools can be changed for (#343).
    isConversationSaved: (id: string) => confirmedConversationIds.has(id),
    answerQuestions,
    decideToolCalls,
    generateImage,
    askSuggestion,
    goFurther,
    regenerateMessage,
    sendFeedback,
    fetchFeedback,
    showSources,
    closeSources,
    showExecutionDetails,
    closeExecutionDetails,
    activeDiscussionScores,
    triggerDiscussionScore,
    refreshDiscussionScores,
    activeDiscussionFeedback,
    submitDiscussionFeedback,
    refreshDiscussionFeedback,
    activeAttachedFiles,
    attachFile,
    attachZip,
    activeImports,
    removeAttachedFile,
    markAttachedFileDismissed,
    dropAttachedFileLocally,
  }
}
