import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { filterLocally, MIN_QUERY_LENGTH, needsServerSearch, SEARCH_DELAY_MS } from '../utils/assistantSearch'
import type { Assistant } from '../types/assistant'
import { useAssistants } from './useAssistants'

// La recherche d'un assistant par sa description (#531), qui fait le moins d'appels possible :
// - une saisie trop courte ne cherche rien (la liste complète s'affiche) ;
// - avec peu d'assistants, le filtre est local : aucune requête ;
// - sinon une seule requête, après une pause de frappe, et la précédente est annulée.
export function useAssistantSearch(source: Ref<Assistant[]>) {
  const { searchAssistants } = useAssistants()
  const query = ref('')
  const serverResults = ref<Assistant[] | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  const active = computed(() => query.value.trim().length >= MIN_QUERY_LENGTH)

  const results = computed<Assistant[]>(() => {
    if (!active.value) return source.value
    if (!needsServerSearch(query.value, source.value.length)) return filterLocally(source.value, query.value)
    // Le serveur n'a pas répondu (encore, ou il est en panne) : le filtre local fait au mieux en attendant.
    return serverResults.value ?? filterLocally(source.value, query.value)
  })

  watch(query, (value) => {
    clearTimeout(timer)
    controller?.abort()
    serverResults.value = null
    loading.value = false
    if (!needsServerSearch(value, source.value.length)) return
    loading.value = true
    timer = setTimeout(async () => {
      controller = new AbortController()
      const found = await searchAssistants(value.trim(), controller.signal)
      if (controller.signal.aborted) return
      serverResults.value = found
      loading.value = false
    }, SEARCH_DELAY_MS)
  })

  onBeforeUnmount(() => {
    clearTimeout(timer)
    controller?.abort()
  })

  return { query, results, active, loading }
}
