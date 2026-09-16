import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

// Factory, pas un singleton : chaque liste paginée (documents, Q/R, chunks,
// runs d'évaluation...) obtient son propre état de page, indépendamment des
// autres. `items` peut changer de longueur en cours de route (ajout,
// suppression) ; la page courante se recale automatiquement si besoin.
export function usePagination<T>(items: Ref<T[]> | ComputedRef<T[]>, pageSize = 6) {
  const page = ref(1)

  const pageCount = computed(() => Math.max(1, Math.ceil(items.value.length / pageSize)))

  const paged = computed(() => {
    const start = (page.value - 1) * pageSize
    return items.value.slice(start, start + pageSize)
  })

  watch(pageCount, (count) => {
    if (page.value > count) page.value = count
  })

  return { page, pageCount, paged }
}
