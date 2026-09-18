<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useCollections } from '../composables/useCollections'
import { useCollectionsBrowser } from '../composables/useCollectionsBrowser'
import CollectionDetailView from './CollectionDetailView.vue'
import PaginationControls from './PaginationControls.vue'

const route = useRoute()
const { collections, isLoading, activeCollection, createCollection, openCollection, closeCollection } =
  useCollections()
const { search, sortKey, page, pageCount, results: sorted, paged } = useCollectionsBrowser(collections)

// Keeps the open/closed collection state in sync with direct URL navigation
// (typed URL, back/forward) - clicks already go through openCollection/closeCollection.
watch(
  () => route.params.id,
  (id) => {
    if (typeof id === 'string') openCollection(id, { navigate: false })
    else closeCollection({ navigate: false })
  },
  { immediate: true },
)

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}

function indexedCount(documents: { status: string }[]) {
  return documents.filter((document) => document.status === 'indexed').length
}
</script>

<template>
  <CollectionDetailView
    v-if="activeCollection"
    :collection="activeCollection"
    :active-document-id="typeof route.params.documentId === 'string' ? route.params.documentId : undefined"
  />

  <section v-else class="collections-view">
    <div class="collections-view__header">
      <h1>Collections</h1>
      <button type="button" class="fr-btn" @click="createCollection">+ Nouvelle collection</button>
    </div>
    <p class="collections-view__intro">
      Regroupez vos documents par sujet pour que l'assistant y réponde de façon ciblée.
    </p>

    <div class="collections-view__toolbar">
      <div class="collections-view__search">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-4.35-4.35M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" />
        </svg>
        <input
          v-model="search"
          type="search"
          placeholder="Rechercher une collection, un tag…"
          aria-label="Rechercher une collection"
        />
      </div>

      <select v-model="sortKey" class="fr-select collections-view__sort" aria-label="Trier les collections">
        <option value="updatedAt">Dernière mise à jour</option>
        <option value="name">Nom</option>
        <option value="documentCount">Nombre de documents</option>
      </select>
    </div>

    <p v-if="isLoading" class="collections-view__empty">Chargement des collections…</p>

    <p v-else-if="sorted.length === 0" class="collections-view__empty">
      Aucune collection ne correspond à cette recherche.
    </p>

    <div v-else class="collections-view__grid">
      <button
        v-for="collection in paged"
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

        <div class="collection-card__name-row">
          <span class="collection-card__name">{{ collection.name }}</span>
          <span
            v-if="!collection.isOwner || collection.visibility === 'public'"
            class="collection-card__badge"
            :class="`collection-card__badge--${collection.isOwner ? 'public' : collection.visibility === 'public' ? 'public' : 'shared'}`"
          >
            {{ !collection.isOwner ? (collection.visibility === 'public' ? 'Publique' : 'Partagée') : 'Publique' }}
          </span>
        </div>
        <span class="collection-card__description">{{ collection.description }}</span>

        <div v-if="collection.tags.length" class="collection-card__tags">
          <span v-for="tag in collection.tags" :key="tag" class="collection-card__tag">{{ tag }}</span>
        </div>

        <div class="collection-card__meta">
          <span>{{ indexedCount(collection.documents) }}/{{ collection.documents.length }} documents indexés</span>
          <span>Mis à jour le {{ formatDate(collection.updatedAt) }}</span>
        </div>
      </button>
    </div>

    <div class="collections-view__pagination">
      <PaginationControls v-model:page="page" :page-count="pageCount" />
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
  max-width: 72rem;
  margin: 0 auto;
}

.collections-view__header h1 {
  margin: 0;
}

.collections-view__intro {
  max-width: 72rem;
  margin: 0.5rem auto 1.5rem;
  color: var(--text-mention-grey);
}

.collections-view__toolbar {
  max-width: 72rem;
  margin: 0 auto 1.5rem;
  display: flex;
  gap: 0.75rem;
}

.collections-view__search {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.875rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-mention-grey);
}

.collections-view__search input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-default-grey);
  font: inherit;
}

.collections-view__search input:focus {
  outline: none;
}

.collections-view__sort {
  width: auto;
}

.collections-view__empty {
  max-width: 72rem;
  margin: 3rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.collections-view__grid {
  max-width: 72rem;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1.25rem;
}

.collection-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.625rem;
  text-align: left;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  cursor: pointer;
  box-sizing: border-box;
}

.collection-card:hover {
  border-color: var(--border-action-high-blue-france);
}

.collection-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 3rem;
  height: 3rem;
  border-radius: 0.625rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-card__name-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.collection-card__name {
  font-size: 1.0625rem;
  font-weight: 700;
}

.collection-card__badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
}

.collection-card__badge--public {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-card__badge--shared {
  background: var(--background-alt-green-emeraude, var(--background-alt-grey));
  color: var(--text-default-success, var(--text-default-grey));
}

.collection-card__description {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.collection-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.collection-card__tag {
  font-size: 0.75rem;
  padding: 0.125rem 0.625rem;
  border-radius: 1rem;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.collection-card__meta {
  margin-top: auto;
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.collections-view__pagination {
  max-width: 72rem;
  margin: 0 auto;
}
</style>
