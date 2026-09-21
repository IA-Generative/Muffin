import { ref, type Ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────

export interface RetrievalMetric {
  collectionId: string
  collectionName: string
  runId: string
  createdAt: string
  pairCount: number
  precisionAtK: number
  recallAtK: number
  mrr: number
  ndcg: number
}

export interface FeedbackMetric {
  upCount: number
  downCount: number
  reasonCounts: Record<string, number>
}

export interface DiscussionMetric {
  totalConversations: number
  coherentCount: number
  avgContextUsageScore: number | null
  avgRating: number | null
  avgMessageCount: number | null
  avgLatencyMs: number | null
  estimatedCost: number | null
}

export interface GroundednessMetric {
  evaluatedCount: number
  ungroundedCount: number
}

export interface DiscussionScoreEntry {
  id: string
  createdAt: string
  llmModel: string
  messageCount: number
  coherent: boolean
  contextUsageScore: number
}

export interface ConversationWithScore {
  id: string
  title: string | null
  createdAt: string
  messageCount: number
  coherent: boolean | null
  contextUsageScore: number | null
  llmModel: string | null
  scores: DiscussionScoreEntry[]
  humanRating: number | null
  humanCoherent: boolean | null
}

export interface QualityOverview {
  retrieval: RetrievalMetric[]
  feedback: FeedbackMetric
  discussion: DiscussionMetric
  groundedness: GroundednessMetric
  conversations: ConversationWithScore[]
  conversationsTotal: number
  conversationsPage: number
}

// ── State ───────────────────────────────────────────────────────────────────

const overview = ref<QualityOverview | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

const scoringConversationIds = ref<Set<string>>(new Set())
const isScoringAll = ref(false)
const currentPage = ref(1)
const pageSize = ref(10)
const currentModelFilter = ref<string | null>(null)

// ── API calls ───────────────────────────────────────────────────────────────

function mapOverview(data: any): QualityOverview {
  return {
    retrieval: (data.retrieval ?? []).map((r: any) => ({
      collectionId: r.collection_id,
      collectionName: r.collection_name,
      runId: r.run_id,
      createdAt: r.created_at,
      pairCount: r.pair_count,
      precisionAtK: r.precision_at_k,
      recallAtK: r.recall_at_k,
      mrr: r.mrr,
      ndcg: r.ndcg,
    })),
    feedback: {
      upCount: data.feedback?.up_count ?? 0,
      downCount: data.feedback?.down_count ?? 0,
      reasonCounts: data.feedback?.reason_counts ?? {},
    },
    discussion: {
      totalConversations: data.discussion?.total_conversations ?? 0,
      coherentCount: data.discussion?.coherent_count ?? 0,
      avgContextUsageScore: data.discussion?.avg_context_usage_score ?? null,
      avgRating: data.discussion?.avg_rating ?? null,
      avgMessageCount: data.discussion?.avg_message_count ?? null,
      avgLatencyMs: data.discussion?.avg_latency_ms ?? null,
      estimatedCost: data.discussion?.estimated_cost ?? null,
    },
    groundedness: {
      evaluatedCount: data.groundedness?.evaluated_count ?? 0,
      ungroundedCount: data.groundedness?.ungrounded_count ?? 0,
    },
    conversations: (data.conversations ?? []).map((c: any) => ({
      id: c.id,
      title: c.title,
      createdAt: c.created_at,
      messageCount: c.message_count,
      coherent: c.coherent,
      contextUsageScore: c.context_usage_score,
      llmModel: c.llm_model,
      scores: (c.scores ?? []).map((s: any) => ({
        id: s.id,
        createdAt: s.created_at,
        llmModel: s.llm_model,
        messageCount: s.message_count,
        coherent: s.coherent,
        contextUsageScore: s.context_usage_score,
      })),
      humanRating: c.human_rating,
      humanCoherent: c.human_coherent,
    })),
    conversationsTotal: data.conversations_total ?? 0,
    conversationsPage: data.conversations_page ?? 1,
  }
}

async function fetchOverview(
  collectionId: string | null = null,
  page: number = 1,
  modelFilter: string | null = null,
) {
  isLoading.value = true
  error.value = null
  currentPage.value = page
  try {
    const url = new URL(`${API_BASE_URL}/api/quality/overview`, window.location.origin)
    if (collectionId) url.searchParams.set('collection_id', collectionId)
    url.searchParams.set('page', String(page))
    url.searchParams.set('page_size', String(pageSize.value))
    if (modelFilter) url.searchParams.set('model_filter', modelFilter)
    const response = await fetch(url.toString(), { credentials: 'include' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    overview.value = mapOverview(await response.json())
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur de chargement'
    overview.value = null
  } finally {
    isLoading.value = false
  }
}

async function scoreConversation(
  conversationId: string,
  model: string | null = null,
) {
  scoringConversationIds.value.add(conversationId)
  // Capture the model currently displayed so we can detect when a new score appears
  const previousModel =
    overview.value?.conversations.find((c) => c.id === conversationId)?.llmModel ??
    null
  try {
    const url = new URL(
      `${API_BASE_URL}/api/quality/conversations/${conversationId}/score`,
      window.location.origin,
    )
    if (model) url.searchParams.set('model', model)
    const response = await fetch(url.toString(), {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    // Poll for the new score to appear (model changes, or score appears if none before)
    await pollConversationScore(conversationId, previousModel)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur de scoring'
  } finally {
    scoringConversationIds.value.delete(conversationId)
  }
}

async function pollConversationScore(
  conversationId: string,
  previousModel: string | null,
  maxAttempts = 60,
) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((resolve) => setTimeout(resolve, 2000))
    if (!scoringConversationIds.value.has(conversationId)) return
    // Re-fetch overview to check if the new score appeared
    const currentCollectionId = overview.value?.retrieval[0]?.collectionId ?? null
    await fetchOverview(currentCollectionId, currentPage.value, currentModelFilter.value)
    const conv = overview.value?.conversations.find((c) => c.id === conversationId)
    // Wait until the conversation has a score AND the model has changed from what we had before
    if (conv?.coherent !== null && conv?.llmModel !== previousModel) return
  }
}

async function scoreAll(
  collectionId: string | null = null,
  model: string | null = null,
) {
  isScoringAll.value = true
  try {
    const url = new URL(`${API_BASE_URL}/api/quality/conversations/score-all`, window.location.origin)
    if (collectionId) url.searchParams.set('collection_id', collectionId)
    if (model) url.searchParams.set('model', model)
    const response = await fetch(url.toString(), {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    const count: number = data.count ?? 0
    if (count === 0) return
    // Poll until all conversations on the current page have scores
    await pollScoreAll(collectionId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Erreur de scoring'
  } finally {
    isScoringAll.value = false
  }
}

async function pollScoreAll(collectionId: string | null, maxAttempts = 120) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    if (!isScoringAll.value) return
    await fetchOverview(collectionId, currentPage.value, currentModelFilter.value)
    // Check if all conversations on the current page have scores
    const convs = overview.value?.conversations ?? []
    if (convs.length > 0 && convs.every((c) => c.coherent !== null)) return
  }
}

function isScoring(conversationId: string): boolean {
  return scoringConversationIds.value.has(conversationId)
}

export function useQuality() {
  return {
    overview: overview as Ref<QualityOverview | null>,
    isLoading,
    error,
    scoringConversationIds,
    isScoringAll,
    currentPage,
    pageSize,
    currentModelFilter,
    fetchOverview,
    scoreConversation,
    scoreAll,
    isScoring,
  }
}
