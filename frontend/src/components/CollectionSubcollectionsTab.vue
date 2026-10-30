<script setup lang="ts">
import { computed } from 'vue'
import { useCollections } from '../composables/useCollections'
import type { Collection } from '../types/collection'

const props = defineProps<{
  collection: Collection
}>()

const { collections, openCollection, createCollection } = useCollections()

// Read from the shared list, which the tab's loader (refreshChildren) fills with every direct
// sub-collection - a sub-collection created or moved here shows up without another fetch.
const children = computed(() =>
  collections.value
    .filter((item) => item.parentId === props.collection.id)
    .sort((a, b) => a.name.localeCompare(b.name)),
)
</script>

<template>
  <div class="subcollections-tab">
    <div class="subcollections-tab__header">
      <p class="subcollections-tab__intro">
        Les sous-collections organisent cette collection comme des dossiers. Chacune a ses propres documents et
        paramètres ; les partages et la visibilité de « {{ collection.name }} » s'y appliquent aussi.
      </p>
      <button
        v-if="collection.canManage"
        type="button"
        class="fr-btn fr-btn--sm subcollections-tab__create"
        @click="createCollection(undefined, undefined, collection.id)"
      >
        + Nouvelle sous-collection
      </button>
    </div>

    <p v-if="children.length === 0" class="subcollections-tab__empty">Aucune sous-collection.</p>

    <ul v-else class="subcollections-tab__list">
      <li v-for="child in children" :key="child.id">
        <button type="button" class="subcollections-tab__row" @click="openCollection(child.id)">
          <span class="subcollections-tab__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="18" height="18">
              <path
                fill="currentColor"
                d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z"
              />
            </svg>
          </span>
          <span class="subcollections-tab__text">
            <span class="subcollections-tab__name">{{ child.name }}</span>
            <span v-if="child.description" class="subcollections-tab__description">{{ child.description }}</span>
          </span>
          <span v-if="child.childrenCount" class="subcollections-tab__count">
            {{ child.childrenCount }} sous-collection{{ child.childrenCount > 1 ? 's' : '' }}
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.subcollections-tab {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.subcollections-tab__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.subcollections-tab__intro {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.subcollections-tab__create {
  flex-shrink: 0;
  white-space: nowrap;
}

.subcollections-tab__empty {
  margin: 2rem 0;
  text-align: center;
  color: var(--text-mention-grey);
}

.subcollections-tab__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.subcollections-tab__row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  text-align: left;
  font: inherit;
  cursor: pointer;
}

.subcollections-tab__row:hover {
  border-color: var(--border-action-high-blue-france);
}

.subcollections-tab__icon {
  display: flex;
  flex-shrink: 0;
  color: var(--text-action-high-blue-france);
}

.subcollections-tab__text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  min-width: 0;
}

.subcollections-tab__name {
  font-weight: 700;
}

.subcollections-tab__description {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subcollections-tab__count {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}
</style>
