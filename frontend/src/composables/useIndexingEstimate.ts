import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { IndexingEstimate } from '../types/collection'
import { READ_EVERYTHING, toPayload, type LongDocumentsDraft } from '../utils/longDocuments'
import { useCollections } from './useCollections'

const ESTIMATE_STEPS: { key: string; label: string }[] = [
  { key: 'summary', label: 'Résumé' },
  { key: 'qa', label: 'Questions-réponses' },
  { key: 'entities', label: 'Entités et relations' },
  { key: 'chunking', label: 'Découpage par le modèle' },
  { key: 'tagging', label: 'Tags' },
]

// Ce que coûterait l'indexation d'un document de `pages` pages avec les réglages tels qu'ils sont saisis (rien
// n'est enregistré), et avec « tout est lu » pour dire ce qui est économisé. Le backend calcule ; ici on ne fait que
// demander, avec un anti-rebond, et ignorer une réponse que la suivante a rendue périmée.
export function useIndexingEstimate(options: {
  collectionId: () => string
  longDocs: () => LongDocumentsDraft
  chunkingStrategy: () => string
  // Faux quand les réglages saisis ne sont pas valides : rien n'est demandé.
  valid: () => boolean
}) {
  const { estimateIndexing } = useCollections()
  const pages = ref<number | ''>(900)
  const state = reactive<{ draft: IndexingEstimate | null; full: IndexingEstimate | null; error: string | null }>({
    draft: null,
    full: null,
    error: null,
  })
  const pagesInvalid = computed(
    () => pages.value === '' || !Number.isInteger(pages.value) || pages.value < 1 || pages.value > 100000,
  )
  let timer: ReturnType<typeof setTimeout> | undefined
  let request = 0

  async function refresh() {
    if (!options.valid() || pagesInvalid.value) return
    const current = ++request
    const draft = toPayload(options.longDocs())
    const [withDraft, withEverything] = await Promise.all([
      estimateIndexing(options.collectionId(), pages.value as number, draft, options.chunkingStrategy()),
      estimateIndexing(
        options.collectionId(),
        pages.value as number,
        { ...draft, ...READ_EVERYTHING },
        options.chunkingStrategy(),
      ),
    ])
    if (current !== request) return
    if ('error' in withDraft) {
      state.error = withDraft.error
      return
    }
    state.error = null
    state.draft = withDraft.estimate
    state.full = 'estimate' in withEverything ? withEverything.estimate : null
  }

  watch(
    [pages, options.longDocs, options.chunkingStrategy, options.collectionId],
    () => {
      clearTimeout(timer)
      timer = setTimeout(refresh, 300)
    },
    { immediate: true, deep: true },
  )
  onBeforeUnmount(() => clearTimeout(timer))

  const steps = computed(() =>
    state.draft
      ? ESTIMATE_STEPS.filter((step) => (state.draft?.chat[step.key] ?? 0) > 0).map((step) => ({
          ...step,
          calls: state.draft?.chat[step.key] ?? 0,
        }))
      : [],
  )
  const embeddings = computed(() =>
    state.draft ? Object.values(state.draft.embeddings).reduce((sum, value) => sum + value, 0) : 0,
  )

  return { pages, pagesInvalid, state, steps, embeddings }
}
