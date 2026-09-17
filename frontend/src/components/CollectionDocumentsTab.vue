<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const { addDocuments, addUrl, removeDocument, documentError } = useCollections()

const documents = computed(() => props.collection.documents)
const { page, pageCount, paged: pagedDocuments } = usePagination(documents)

const urlDraft = ref('')
const isDragging = ref(false)

function submitUrl() {
  if (!urlDraft.value.trim()) return
  addUrl(props.collection.id, urlDraft.value)
  urlDraft.value = ''
}

function handleFiles(files: FileList | null) {
  if (!files?.length) return
  addDocuments(props.collection.id, Array.from(files))
}

function onDrop(event: DragEvent) {
  isDragging.value = false
  handleFiles(event.dataTransfer?.files ?? null)
}

const STATUS_LABEL = {
  pending: 'En attente',
  indexing: 'Indexation…',
  indexed: 'Indexé',
  error: 'Erreur',
} as const
</script>

<template>
  <div>
    <div
      class="documents-tab__dropzone"
      :class="{ 'documents-tab__dropzone--active': isDragging }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="onDrop"
    >
      <input
        type="file"
        multiple
        class="documents-tab__file-input"
        aria-label="Choisir des fichiers à ajouter"
        @change="handleFiles(($event.target as HTMLInputElement).files)"
      />
      <p>Glissez des fichiers ici, ou <span class="documents-tab__browse">cliquez pour parcourir</span></p>
    </div>

    <form class="documents-tab__url-form" @submit.prevent="submitUrl">
      <input
        v-model="urlDraft"
        type="url"
        placeholder="Ajouter une URL à indexer…"
        aria-label="URL à indexer"
      />
      <button type="submit" class="fr-btn fr-btn--secondary" :disabled="!urlDraft.trim()">Ajouter</button>
    </form>

    <p v-if="documentError" class="documents-tab__error" role="alert">{{ documentError }}</p>

    <ul v-if="collection.documents.length" class="documents-tab__list">
      <li v-for="document in pagedDocuments" :key="document.id" class="documents-tab__item">
        <span class="documents-tab__item-icon" aria-hidden="true">
          <svg v-if="document.type === 'file'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6M13.5 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5L13.5 3Z" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
          </svg>
        </span>

        <div class="documents-tab__item-body">
          <span class="documents-tab__item-name">{{ document.name }}</span>
          <div class="documents-tab__progress-track">
            <div
              class="documents-tab__progress-bar"
              :class="`documents-tab__progress-bar--${document.status}`"
              :style="{ width: `${document.progress}%` }"
            />
          </div>
        </div>

        <span class="documents-tab__item-status" :class="`documents-tab__item-status--${document.status}`">
          {{ STATUS_LABEL[document.status] }}
        </span>

        <button
          type="button"
          class="documents-tab__item-remove"
          :aria-label="`Retirer ${document.name}`"
          @click="removeDocument(collection.id, document.id)"
        >
          ✕
        </button>
      </li>
    </ul>
    <p v-else class="documents-tab__empty">Aucun document pour le moment.</p>

    <PaginationControls v-model:page="page" :page-count="pageCount" />
  </div>
</template>

<style scoped>
.documents-tab__dropzone {
  padding: 1.75rem;
  text-align: center;
  border: 2px dashed var(--border-default-grey);
  border-radius: 0.5rem;
  color: var(--text-mention-grey);
  cursor: pointer;
  position: relative;
}

.documents-tab__dropzone--active {
  border-color: var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
}

.documents-tab__browse {
  color: var(--text-action-high-blue-france);
  text-decoration: underline;
}

.documents-tab__file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.documents-tab__url-form {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.documents-tab__url-form input {
  flex: 1;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.documents-tab__error {
  margin: 0.75rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.documents-tab__list {
  list-style: none;
  margin: 1.25rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.documents-tab__empty {
  margin-top: 1.25rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.documents-tab__item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.documents-tab__item-icon {
  flex-shrink: 0;
  display: flex;
  color: var(--text-mention-grey);
}

.documents-tab__item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.documents-tab__item-name {
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.documents-tab__progress-track {
  height: 0.25rem;
  border-radius: 0.125rem;
  background: var(--background-alt-grey);
  overflow: hidden;
}

.documents-tab__progress-bar {
  height: 100%;
  border-radius: 0.125rem;
  background: var(--background-action-high-blue-france);
  transition: width 0.3s ease;
}

.documents-tab__progress-bar--indexed {
  background: var(--background-action-high-success);
}

.documents-tab__item-status {
  flex-shrink: 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.documents-tab__item-status--indexed {
  color: var(--text-default-success);
}

.documents-tab__item-remove {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}
</style>
