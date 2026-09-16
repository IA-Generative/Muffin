<script setup lang="ts">
const page = defineModel<number>('page', { required: true })

defineProps<{
  pageCount: number
}>()
</script>

<template>
  <nav v-if="pageCount > 1" class="pagination-controls" aria-label="Pagination">
    <button type="button" :disabled="page === 1" @click="page--">Précédent</button>
    <span>Page {{ page }} / {{ pageCount }}</span>
    <button type="button" :disabled="page === pageCount" @click="page++">Suivant</button>
  </nav>
</template>

<style scoped>
.pagination-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1.5rem;
}

.pagination-controls button {
  padding: 0.375rem 0.875rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
}

.pagination-controls button:disabled {
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}

.pagination-controls span {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}
</style>
