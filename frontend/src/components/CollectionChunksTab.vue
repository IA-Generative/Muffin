<script setup lang="ts">
import { computed } from 'vue'
import { usePagination } from '../composables/usePagination'
import type { Collection } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const chunks = computed(() => props.collection.chunks)
const { page, pageCount, paged: pagedChunks } = usePagination(chunks)
</script>

<template>
  <div>
    <p class="chunks-tab__intro">
      Extraits générés à partir des documents indexés, selon la stratégie de découpage définie dans
      l'onglet Paramètres.
    </p>

    <ul v-if="collection.chunks.length" class="chunks-tab__list">
      <li v-for="item in pagedChunks" :key="item.id" class="chunks-tab__item">
        <div class="chunks-tab__item-header">
          <span class="chunks-tab__item-source">{{ item.documentName }} · chunk {{ item.index + 1 }}</span>
          <span class="chunks-tab__item-tokens">{{ item.tokenCount }} tokens</span>
        </div>
        <p class="chunks-tab__item-text">{{ item.text }}</p>
      </li>
    </ul>
    <p v-else class="chunks-tab__empty">
      Aucun chunk pour le moment. Ils apparaissent une fois les documents indexés.
    </p>

    <PaginationControls v-model:page="page" :page-count="pageCount" />
  </div>
</template>

<style scoped>
.chunks-tab__intro {
  margin: 0 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.chunks-tab__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chunks-tab__item {
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.chunks-tab__item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.375rem;
}

.chunks-tab__item-source {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--text-mention-grey);
}

.chunks-tab__item-tokens {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.chunks-tab__item-text {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.5;
}

.chunks-tab__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}
</style>
