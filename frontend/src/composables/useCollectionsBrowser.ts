import { computed, ref, watch, type Ref } from 'vue'
import type { Collection } from '../types/collection'
import { usePagination } from './usePagination'

export type CollectionSortKey = 'updatedAt' | 'name' | 'documentCount'

// Factory, pas un singleton : chaque vue qui parcourt une liste de
// collections obtient son propre état de recherche/tri/pagination.
export function useCollectionsBrowser(source: Ref<Collection[]>) {
  const search = ref('')
  const sortKey = ref<CollectionSortKey>('updatedAt')

  const filtered = computed(() => {
    const query = search.value.trim().toLowerCase()
    if (!query) return source.value
    return source.value.filter(
      (collection) =>
        collection.name.toLowerCase().includes(query) ||
        collection.description.toLowerCase().includes(query) ||
        collection.tags.some((tag) => tag.toLowerCase().includes(query)),
    )
  })

  const sorted = computed(() => {
    const list = [...filtered.value]
    switch (sortKey.value) {
      case 'name':
        return list.sort((a, b) => a.name.localeCompare(b.name))
      case 'documentCount':
        return list.sort((a, b) => b.documents.length - a.documents.length)
      default:
        return list.sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    }
  })

  const { page, pageCount, paged } = usePagination(sorted)

  watch([search, sortKey], () => (page.value = 1))

  return { search, sortKey, page, pageCount, results: sorted, paged }
}
