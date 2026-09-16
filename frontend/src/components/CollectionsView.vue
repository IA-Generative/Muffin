<script setup lang="ts">
import { useCollections } from '../composables/useCollections'

const { collections, createCollection, openCollection } = useCollections()
</script>

<template>
  <section class="collections-view">
    <div class="collections-view__header">
      <h1>Collections</h1>
      <button type="button" class="fr-btn" @click="createCollection">+ Nouvelle collection</button>
    </div>
    <p class="collections-view__intro">
      Regroupez vos documents par sujet pour que l'assistant y réponde de façon ciblée.
    </p>

    <div class="collections-view__grid">
      <button
        v-for="collection in collections"
        :key="collection.id"
        type="button"
        class="collection-card"
        @click="openCollection(collection.id)"
      >
        <span class="collection-card__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22">
            <path
              fill="currentColor"
              d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z"
            />
          </svg>
        </span>
        <span class="collection-card__name">{{ collection.name }}</span>
        <span class="collection-card__description">{{ collection.description }}</span>
        <span class="collection-card__count">{{ collection.documentCount }} document(s)</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.collections-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.collections-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 60rem;
  margin: 0 auto;
}

.collections-view__header h1 {
  margin: 0;
}

.collections-view__intro {
  max-width: 60rem;
  margin: 0.5rem auto 2rem;
  color: var(--text-mention-grey);
}

.collections-view__grid {
  max-width: 60rem;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.collection-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  text-align: left;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  cursor: pointer;
}

.collection-card:hover {
  border-color: var(--border-action-high-blue-france);
}

.collection-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 0.5rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-card__name {
  font-weight: 700;
}

.collection-card__description {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.collection-card__count {
  margin-top: auto;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}
</style>
