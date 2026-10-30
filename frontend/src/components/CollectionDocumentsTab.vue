<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { isImportFinished, isZip, useCollectionImports } from '../composables/useCollectionImports'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection } from '../types/collection'
import type { RefreshSchedule } from '../utils/refreshSchedule'
import AddUrlModal from './AddUrlModal.vue'
import CollectionImportStatus from './CollectionImportStatus.vue'
import DocumentDetailModal from './DocumentDetailModal.vue'
import DuplicateDocumentsModal from './DuplicateDocumentsModal.vue'
import NewMarkdownDocumentModal from './NewMarkdownDocumentModal.vue'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
  activeDocumentId?: string
}>()

const router = useRouter()
const {
  addDocuments,
  addLivingDocuments,
  createMarkdownDocument,
  reloadDocuments,
  addUrl,
  pendingDuplicates,
  confirmDuplicates,
  dismissDuplicates,
  removeDocument,
  documentError,
  refreshChildren,
  reprocessDocument,
  reprocessFailedDocuments,
} = useCollections()
const { imports, startImport } = useCollectionImports()

// ZIPs dropped here during this visit (#223) - each becomes a sub-collection of this one.
const importIds = ref<string[]>([])
const tabImports = computed(() => importIds.value.map((id) => imports.value[id]).filter((item) => item !== undefined))

async function importZip(file: File) {
  const started = await startImport(file, { parentId: props.collection.id })
  importIds.value = [started.id, ...importIds.value]
}

// The new sub-collection shows in the Sous-collections tab as soon as its import is done.
watch(
  () => tabImports.value.filter(isImportFinished).length,
  () => refreshChildren(props.collection.id),
)

const documents = computed(() => props.collection.documents)
const { page, pageCount, paged: pagedDocuments } = usePagination(documents)

const urlDraft = ref('')
const isDragging = ref(false)

// Route-driven (see /collections/:id/documents/:documentId) rather than plain local state - a
// direct link/refresh reopens the same document, and opening/closing pushes the URL rather than
// just toggling a ref, so the modal is actually shareable/bookmarkable.
const openDocument = computed(() => documents.value.find((document) => document.id === props.activeDocumentId))

function openDocumentModal(documentId: string) {
  router.push(`/collections/${props.collection.id}/documents/${documentId}`)
}

function closeDocumentModal() {
  router.push(`/collections/${props.collection.id}`)
}

// What this collection refused as already there (#300), waiting for the user to decide.
const duplicates = computed(() =>
  pendingDuplicates.value.filter((duplicate) => duplicate.collectionId === props.collection.id),
)

// The URL waiting for the modal that asks when it is fetched again (#19).
const pendingUrl = ref<string | null>(null)

function submitUrl() {
  if (!urlDraft.value.trim()) return
  pendingUrl.value = urlDraft.value.trim()
}

function confirmUrl(schedule: RefreshSchedule | null) {
  if (pendingUrl.value === null) return
  addUrl(props.collection.id, pendingUrl.value, schedule)
  pendingUrl.value = null
  urlDraft.value = ''
}

function handleFiles(files: FileList | null) {
  if (!files?.length) return
  const all = Array.from(files)
  all.filter(isZip).forEach(importZip)
  const documents = all.filter((file) => !isZip(file))
  if (documents.length) addDocuments(props.collection.id, documents)
}

const showMarkdownModal = ref(false)

async function createMarkdown(name: string, content: string) {
  if (await createMarkdownDocument(props.collection.id, name, content)) showMarkdownModal.value = false
}

function closeMarkdownModal() {
  showMarkdownModal.value = false
  documentError.value = null
}

function handleLivingFiles(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) addLivingDocuments(props.collection.id, Array.from(input.files))
  input.value = '' // lets the same file be picked again after a refusal
}

function onDrop(event: DragEvent) {
  isDragging.value = false
  handleFiles(event.dataTransfer?.files ?? null)
}

// The documents that ended in error (#340): one click relaunches them all, or each by its own button.
const failedCount = computed(() => documents.value.filter((document) => document.status === 'error').length)
const relaunched = ref<number | null>(null)

async function relaunchAll() {
  relaunched.value = await reprocessFailedDocuments(props.collection.id)
}

async function relaunch(documentId: string) {
  relaunched.value = null
  await reprocessDocument(props.collection.id, documentId)
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
      <p class="documents-tab__dropzone-hint">Une archive .zip devient une sous-collection, avec toute son arborescence.</p>
    </div>

    <div v-if="tabImports.length" class="documents-tab__imports">
      <CollectionImportStatus v-for="item in tabImports" :key="item.id" :item="item" />
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
    <DuplicateDocumentsModal
      v-if="duplicates.length"
      :duplicates="duplicates"
      @confirm="confirmDuplicates(collection.id)"
      @cancel="dismissDuplicates(collection.id)"
    />
    <AddUrlModal v-if="pendingUrl !== null" :url="pendingUrl" @add="confirmUrl" @cancel="pendingUrl = null" />

    <div v-if="collection.canEdit" class="documents-tab__living">
      <label class="fr-btn fr-btn--secondary fr-btn--sm documents-tab__living-button">
        Ajouter un document vivant
        <input
          type="file"
          multiple
          accept=".odt,.md"
          class="documents-tab__file-input"
          aria-label="Choisir des documents vivants à ajouter (.odt ou .md)"
          @change="handleLivingFiles"
        />
      </label>
      <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="showMarkdownModal = true">
        Créer un document Markdown
      </button>
      <p class="documents-tab__living-hint">
        ODT ou Markdown. Un document vivant se remplace par une nouvelle version, avec historique, sans le supprimer.
      </p>
    </div>

    <p v-if="documentError && !showMarkdownModal" class="documents-tab__error" role="alert">{{ documentError }}</p>

    <div v-if="collection.canManage && failedCount" class="documents-tab__failed">
      <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="relaunchAll">
        Relancer {{ failedCount > 1 ? `les ${failedCount} documents en erreur` : 'le document en erreur' }}
      </button>
    </div>
    <p v-if="relaunched !== null" class="documents-tab__relaunched" role="status">
      {{ relaunched > 1 ? `${relaunched} documents relancés.` : `${relaunched} document relancé.` }}
    </p>

    <ul v-if="collection.documents.length" class="documents-tab__list">
      <li v-for="document in pagedDocuments" :key="document.id" class="documents-tab__item">
        <button
          type="button"
          class="documents-tab__item-open"
          :aria-label="`Voir le détail de ${document.name}`"
          @click="openDocumentModal(document.id)"
        >
          <span class="documents-tab__item-icon" aria-hidden="true">
            <svg v-if="document.type === 'file'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6M13.5 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5L13.5 3Z" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
            </svg>
          </span>

          <span class="documents-tab__item-body">
            <span class="documents-tab__item-name">
              {{ document.name }}
              <span v-if="document.kind === 'living'" class="documents-tab__living-badge">Document vivant</span>
            </span>
            <span class="documents-tab__progress-track">
              <span
                class="documents-tab__progress-bar"
                :class="`documents-tab__progress-bar--${document.status}`"
                :style="{ width: `${document.progress}%` }"
              />
            </span>
          </span>

          <span class="documents-tab__item-status" :class="`documents-tab__item-status--${document.status}`">
            {{ STATUS_LABEL[document.status] }}
          </span>
        </button>

        <button
          v-if="collection.canManage && document.status === 'error'"
          type="button"
          class="fr-btn fr-btn--tertiary fr-btn--sm documents-tab__item-retry"
          :aria-label="`Réessayer l'indexation de ${document.name}`"
          @click="relaunch(document.id)"
        >
          Réessayer
        </button>

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

    <NewMarkdownDocumentModal
      v-if="showMarkdownModal"
      :error="documentError"
      @create="createMarkdown"
      @cancel="closeMarkdownModal"
    />

    <DocumentDetailModal
      v-if="openDocument"
      :collection-id="collection.id"
      :document="openDocument"
      :editable="collection.canManage"
      :can-edit-living="collection.canEdit"
      @close="closeDocumentModal"
      @changed="reloadDocuments(collection.id)"
    />
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

.documents-tab__living {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.documents-tab__living-button {
  position: relative;
  cursor: pointer;
}

.documents-tab__living-hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.documents-tab__living-badge {
  margin-left: 0.5rem;
  padding: 0 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-contrast-info);
  color: var(--text-default-info);
  font-size: 0.75rem;
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

.documents-tab__item-open {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  padding: 0;
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
  display: block;
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.documents-tab__progress-track {
  display: block;
  height: 0.25rem;
  border-radius: 0.125rem;
  background: var(--background-alt-grey);
  overflow: hidden;
}

.documents-tab__progress-bar {
  display: block;
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

.documents-tab__failed {
  margin-top: 0.75rem;
}

.documents-tab__relaunched {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.documents-tab__item-retry {
  flex-shrink: 0;
}

.documents-tab__item-status--error {
  color: var(--text-default-error);
}

.documents-tab__item-remove {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.documents-tab__dropzone-hint {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.documents-tab__imports {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
</style>
