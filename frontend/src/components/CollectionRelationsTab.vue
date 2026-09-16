<script setup lang="ts">
import { computed } from 'vue'
import { usePagination } from '../composables/usePagination'
import type { Collection, EntityType } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const entities = computed(() => props.collection.entities)
const { page: entityPage, pageCount: entityPageCount, paged: pagedEntities } = usePagination(entities)

const relations = computed(() => props.collection.relations)
const { page: relationPage, pageCount: relationPageCount, paged: pagedRelations } = usePagination(relations)

const ENTITY_LABEL: Record<EntityType, string> = {
  personne: 'Personne',
  organisation: 'Organisation',
  lieu: 'Lieu',
  date: 'Date',
  autre: 'Autre',
}
</script>

<template>
  <div>
    <h3 class="relations-tab__title">Entités</h3>
    <p class="relations-tab__intro">Entités reconnues dans les documents de cette collection.</p>

    <ul v-if="collection.entities.length" class="relations-tab__entities">
      <li v-for="item in pagedEntities" :key="item.id" class="relations-tab__entity">
        <span class="relations-tab__entity-type" :class="`relations-tab__entity-type--${item.type}`">
          {{ ENTITY_LABEL[item.type] }}
        </span>
        <span class="relations-tab__entity-name">{{ item.name }}</span>
        <span class="relations-tab__entity-mentions">{{ item.mentions }} mention(s)</span>
      </li>
    </ul>
    <p v-else class="relations-tab__empty">Aucune entité détectée pour le moment.</p>
    <PaginationControls v-model:page="entityPage" :page-count="entityPageCount" />

    <h3 class="relations-tab__title">Relations</h3>
    <p class="relations-tab__intro">
      Relations détectées automatiquement entre les documents de cette collection.
    </p>

    <ul v-if="collection.relations.length" class="relations-tab__list">
      <li v-for="relation in pagedRelations" :key="relation.id" class="relations-tab__item">
        <span class="relations-tab__node">{{ relation.from }}</span>
        <span class="relations-tab__link">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H12a6 6 0 0 0 0 12h1.5m-3-6h7.5m0 0-3-3m3 3-3 3" />
          </svg>
          {{ relation.type }}
        </span>
        <span class="relations-tab__node">{{ relation.to }}</span>
      </li>
    </ul>
    <p v-else class="relations-tab__empty">
      Aucune relation détectée pour le moment. Elles apparaissent une fois les documents indexés.
    </p>
    <PaginationControls v-model:page="relationPage" :page-count="relationPageCount" />
  </div>
</template>

<style scoped>
.relations-tab__title {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}

.relations-tab__title + .relations-tab__intro {
  margin-top: 0;
}

.relations-tab__intro {
  margin: 2rem 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.relations-tab__entities {
  list-style: none;
  margin: 0 0 2rem;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.relations-tab__entity {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 1rem;
  font-size: 0.8125rem;
}

.relations-tab__entity-type {
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.relations-tab__entity-type--personne {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.relations-tab__entity-type--organisation {
  background: var(--background-alt-green-emeraude);
  color: var(--text-default-success);
}

.relations-tab__entity-name {
  font-weight: 700;
}

.relations-tab__entity-mentions {
  color: var(--text-mention-grey);
}

.relations-tab__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.relations-tab__item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  font-size: 0.875rem;
}

.relations-tab__node {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.relations-tab__link {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  color: var(--text-mention-grey);
  font-size: 0.8125rem;
}

.relations-tab__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}
</style>
