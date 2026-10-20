<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import type { Collection } from '../types/collection'
import { collectionPathLabel } from '../utils/collectionPath'

const props = defineProps<{
  collection: Collection
}>()

const emit = defineEmits<{
  close: []
}>()

const { collections, moveCollection, moveError } = useCollections()

const search = ref('')
const isMoving = ref(false)

// Only collections the user owns can receive another one (#215), never the collection itself nor
// anything below it - the backend refuses those too, this just doesn't offer them.
const targets = computed(() => {
  const query = search.value.trim().toLowerCase()
  return collections.value
    .filter(
      (item) =>
        item.isOwner &&
        item.id !== props.collection.id &&
        !item.path.some((ancestor) => ancestor.id === props.collection.id),
    )
    .map((item) => ({ collection: item, label: collectionPathLabel(item) }))
    .filter((target) => !query || target.label.toLowerCase().includes(query))
    .sort((a, b) => a.label.localeCompare(b.label))
})

async function moveTo(parentId: string | null) {
  if (parentId === props.collection.parentId) return
  isMoving.value = true
  const moved = await moveCollection(props.collection.id, parentId)
  isMoving.value = false
  if (moved) emit('close')
}

moveError.value = null
</script>

<template>
  <div class="move-collection-overlay" @click.self="emit('close')">
    <div class="move-collection-modal" role="dialog" aria-modal="true" aria-labelledby="move-collection-title">
      <header class="move-collection-modal__header">
        <h2 id="move-collection-title" class="move-collection-modal__title">Déplacer « {{ collection.name }} »</h2>
        <button type="button" class="move-collection-modal__close" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>

      <p class="move-collection-modal__hint">
        Ses sous-collections la suivent. Elle prend les partages et la visibilité de sa nouvelle collection parente.
      </p>

      <input
        v-model="search"
        type="text"
        class="move-collection-modal__search"
        placeholder="Rechercher une collection…"
        aria-label="Rechercher une collection"
      />

      <ul class="move-collection-modal__list">
        <li>
          <button
            type="button"
            class="move-collection-modal__row"
            :disabled="isMoving || collection.parentId === null"
            @click="moveTo(null)"
          >
            Premier niveau (aucune collection parente)
            <span v-if="collection.parentId === null" class="move-collection-modal__current">actuel</span>
          </button>
        </li>
        <li v-for="target in targets" :key="target.collection.id">
          <button
            type="button"
            class="move-collection-modal__row"
            :disabled="isMoving || target.collection.id === collection.parentId"
            @click="moveTo(target.collection.id)"
          >
            {{ target.label }}
            <span v-if="target.collection.id === collection.parentId" class="move-collection-modal__current">actuel</span>
          </button>
        </li>
      </ul>

      <p v-if="moveError" class="move-collection-modal__error">{{ moveError }}</p>
    </div>
  </div>
</template>

<style scoped>
.move-collection-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(0 0 0 / 40%);
}

.move-collection-modal {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: min(32rem, calc(100vw - 2rem));
  max-height: 80vh;
  padding: 1.25rem;
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.move-collection-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.move-collection-modal__title {
  margin: 0;
  font-size: 1.125rem;
}

.move-collection-modal__close {
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.move-collection-modal__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.move-collection-modal__search {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.move-collection-modal__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.move-collection-modal__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  text-align: left;
  font: inherit;
  cursor: pointer;
}

.move-collection-modal__row:hover:not(:disabled) {
  background: var(--background-alt-grey-hover);
}

.move-collection-modal__row:disabled {
  cursor: default;
  color: var(--text-mention-grey);
}

.move-collection-modal__current {
  flex-shrink: 0;
  font-size: 0.75rem;
}

.move-collection-modal__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}
</style>
