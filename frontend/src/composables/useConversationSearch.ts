import { onBeforeUnmount, ref, watch } from 'vue'
import { isSearchable, normalizeQuery } from '../utils/conversationSearch'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const PAGE_SIZE = 20
// Waits for the typing to pause: one request per word typed would only make the sidebar flicker.
const DEBOUNCE_MS = 250

export interface ConversationSearchHit {
  id: string
  title: string | null
  updated_at: string
  title_matched: boolean
  message_id: string | null
  snippet: string | null
}

// The search of the conversations in the sidebar (#509): what is typed, the hits for it, and the next page on demand.
export function useConversationSearch() {
  const query = ref('')
  const hits = ref<ConversationSearchHit[]>([])
  const total = ref(0)
  const loading = ref(false)
  const failed = ref(false)
  // A search is on once a query long enough is typed: the sidebar shows its hits instead of the history.
  const active = ref(false)

  let page = 1
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  async function load(nextPage: number) {
    controller?.abort()
    controller = new AbortController()
    const mine = controller
    loading.value = true
    failed.value = false
    try {
      const params = new URLSearchParams({
        q: normalizeQuery(query.value),
        page: String(nextPage),
        page_size: String(PAGE_SIZE),
      })
      const response = await fetch(`${API_BASE_URL}/api/conversations/search?${params}`, {
        credentials: 'include',
        signal: mine.signal,
      })
      if (!response.ok) throw new Error(`${response.status}`)
      const body: { items: ConversationSearchHit[]; total: number } = await response.json()
      hits.value = nextPage === 1 ? body.items : [...hits.value, ...body.items]
      total.value = body.total
      page = nextPage
    } catch (error) {
      if ((error as Error).name === 'AbortError') return // a newer search took over: it owns the state now
      failed.value = true
    } finally {
      if (controller === mine) loading.value = false
    }
  }

  function clear() {
    clearTimeout(timer)
    controller?.abort()
    query.value = ''
    hits.value = []
    total.value = 0
    loading.value = false
    failed.value = false
    active.value = false
    page = 1
  }

  function loadMore() {
    if (!loading.value && hits.value.length < total.value) void load(page + 1)
  }

  watch(query, (value) => {
    clearTimeout(timer)
    if (!isSearchable(value)) {
      controller?.abort()
      hits.value = []
      total.value = 0
      loading.value = false
      failed.value = false
      active.value = false
      return
    }
    active.value = true
    loading.value = true
    timer = setTimeout(() => void load(1), DEBOUNCE_MS)
  })

  onBeforeUnmount(() => {
    clearTimeout(timer)
    controller?.abort()
  })

  return { query, hits, total, loading, failed, active, clear, loadMore }
}
