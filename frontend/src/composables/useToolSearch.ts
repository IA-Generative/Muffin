import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import type { Tool } from '../types/tool'
import { filterLocally, MIN_QUERY_LENGTH, needsServerSearch, SEARCH_DELAY_MS } from '../utils/toolSearch'
import { useTools } from './useTools'

// La recherche d'un outil par ce qu'il fait (#530), qui fait le moins d'appels possible :
// - une saisie trop courte ne cherche rien (la liste complète s'affiche) ;
// - avec peu d'outils, le filtre est local : aucune requête ;
// - sinon une seule requête, après une pause de frappe, et la précédente est annulée.
// Le serveur ne fait que classer parmi les outils que la personne peut utiliser : ses réponses sont rapprochées de la
// liste déjà chargée, si bien qu'un outil absent de cette liste n'apparaît jamais.
export function useToolSearch(source: Ref<Tool[]>, conversationId?: Ref<string | undefined>) {
  const { searchTools } = useTools()
  const query = ref('')
  const serverRefs = ref<string[] | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined

  const active = computed(() => query.value.trim().length >= MIN_QUERY_LENGTH)

  const results = computed<Tool[]>(() => {
    if (!active.value) return source.value
    if (!needsServerSearch(query.value, source.value.length)) return filterLocally(source.value, query.value)
    if (serverRefs.value === null) return filterLocally(source.value, query.value)
    const byRef = new Map(source.value.map((tool) => [tool.ref, tool]))
    return serverRefs.value.flatMap((ref_) => byRef.get(ref_) ?? [])
  })

  watch(query, (value) => {
    clearTimeout(timer)
    controller?.abort()
    serverRefs.value = null
    loading.value = false
    if (!needsServerSearch(value, source.value.length)) return
    loading.value = true
    timer = setTimeout(async () => {
      controller = new AbortController()
      const found = await searchTools(value.trim(), conversationId?.value, controller.signal)
      if (controller.signal.aborted) return
      serverRefs.value = found ? found.map((tool) => tool.ref) : null
      loading.value = false
    }, SEARCH_DELAY_MS)
  })

  onBeforeUnmount(() => {
    clearTimeout(timer)
    controller?.abort()
  })

  return { query, results, active, loading }
}
