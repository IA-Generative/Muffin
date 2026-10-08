<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  LivingDocumentError,
  useLivingDocuments,
  type DocumentLock,
  type DocumentRevision,
} from '../composables/useLivingDocuments'

const props = defineProps<{
  collectionId: string
  documentId: string
  // Only the collection owner can replace/restore - same gating as every other write in the UI.
  editable: boolean
}>()

const emit = defineEmits<{
  // A write went through: the parent refreshes the document (it is being reindexed).
  changed: []
}>()

const { fetchRevisions, fetchLock, replaceDocument, restoreRevision, downloadDocument } = useLivingDocuments()

const revisions = ref<DocumentRevision[]>()
const lock = ref<DocumentLock | null>(null)
const loadError = ref(false)
const actionError = ref<string | null>(null)
const isBusy = ref(false)

const current = computed(() => revisions.value?.find((revision) => revision.isCurrent))
// Someone (possibly this very user, elsewhere) is editing: writes would be refused anyway.
const isLocked = computed(() => lock.value !== null)

const ORIGIN_LABEL: Record<DocumentRevision['origin'], string> = {
  upload: 'Remplacement par fichier',
  chat: 'Modification via le chat',
  ui: 'Modification manuelle',
  restore: 'Restauration',
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

async function load() {
  try {
    const [loadedRevisions, loadedLock] = await Promise.all([
      fetchRevisions(props.collectionId, props.documentId),
      fetchLock(props.collectionId, props.documentId),
    ])
    revisions.value = loadedRevisions
    lock.value = loadedLock
    loadError.value = false
  } catch {
    loadError.value = true
  }
}

// Runs a write, then reloads. A stale write (someone else got there first, or the lock lapsed)
// still reloads, so the user sees the state their retry will be based on.
async function run(action: () => Promise<void>) {
  actionError.value = null
  isBusy.value = true
  try {
    await action()
    emit('changed')
  } catch (error) {
    actionError.value = error instanceof LivingDocumentError ? error.message : 'L’opération a échoué.'
  } finally {
    await load()
    isBusy.value = false
  }
}

// Read-only, so it stays available to everyone who can open the panel, even while the document
// is locked or being reindexed.
async function download(revision?: DocumentRevision) {
  actionError.value = null
  const target = revision ?? current.value
  try {
    await downloadDocument(props.collectionId, props.documentId, target?.filename ?? 'document', revision?.number)
  } catch (error) {
    actionError.value = error instanceof LivingDocumentError ? error.message : 'Le téléchargement a échoué.'
  }
}

function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // lets the same file be picked again after a refusal
  if (!file || !current.value) return
  const baseRevision = current.value.number
  run(() => replaceDocument(props.collectionId, props.documentId, file, baseRevision))
}

function restore(revision: DocumentRevision) {
  if (!current.value) return
  const baseRevision = current.value.number
  run(() => restoreRevision(props.collectionId, props.documentId, revision.number, baseRevision))
}

// The lock indicator and history stay fresh without a reload - someone else may take or release
// the lock while this panel is open.
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  load()
  timer = setInterval(load, 10_000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <section class="revisions">
    <p v-if="loadError" class="revisions__error" role="alert">Impossible de charger l'historique.</p>
    <p v-else-if="!revisions" class="revisions__loading">Chargement…</p>

    <template v-else>
      <p v-if="lock" class="revisions__lock" role="status">
        <span aria-hidden="true">🔒</span>
        En cours de modification
        {{ lock.heldByMe ? 'dans une autre session de votre compte' : `par ${lock.lockedByDisplay ?? 'quelqu’un'}` }}
        jusqu'à {{ formatTime(lock.expiresAt) }}.
      </p>

      <div class="revisions__actions">
        <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="download()">
          Télécharger la version courante
        </button>
      </div>

      <div v-if="editable" class="revisions__replace">
        <label class="fr-btn fr-btn--secondary revisions__replace-button" :class="{ 'revisions__replace-button--disabled': isBusy || isLocked }">
          Remplacer par une nouvelle version
          <input
            type="file"
            class="revisions__file-input"
            accept=".odt,.md"
            :disabled="isBusy || isLocked"
            aria-label="Choisir la nouvelle version du document (.odt ou .md)"
            @change="onFileSelected"
          />
        </label>
        <p class="revisions__hint">
          Le nouveau fichier doit être de même format ({{ current?.format === 'md' ? 'Markdown' : 'ODT' }}). Le document est
          ré-indexé, l'historique est conservé.
        </p>
      </div>

      <p v-if="actionError" class="revisions__error" role="alert">{{ actionError }}</p>

      <ol class="revisions__list" aria-label="Historique des révisions">
        <li v-for="revision in revisions" :key="revision.number" class="revisions__item">
          <div class="revisions__item-main">
            <span class="revisions__number">Révision {{ revision.number }}</span>
            <span v-if="revision.isCurrent" class="revisions__badge">Courante</span>
            <span class="revisions__origin">
              {{ ORIGIN_LABEL[revision.origin] }}
              <template v-if="revision.restoredFromNumber">(révision {{ revision.restoredFromNumber }})</template>
            </span>
            <span class="revisions__meta">
              {{ revision.filename }} · {{ revision.createdByDisplay ?? 'inconnu' }} · {{ formatDate(revision.createdAt) }}
            </span>
          </div>
          <div class="revisions__item-actions">
            <button
              type="button"
              class="fr-btn fr-btn--tertiary fr-btn--sm"
              :aria-label="`Télécharger la révision ${revision.number}`"
              @click="download(revision)"
            >
              Télécharger
            </button>
            <button
              v-if="editable && !revision.isCurrent"
              type="button"
              class="fr-btn fr-btn--tertiary fr-btn--sm"
              :disabled="isBusy || isLocked"
              @click="restore(revision)"
            >
              Restaurer
            </button>
          </div>
        </li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.revisions__loading,
.revisions__hint,
.revisions__meta {
  color: var(--text-mention-grey);
  font-size: 0.8125rem;
}

.revisions__error {
  color: var(--text-default-error);
  font-size: 0.875rem;
}

.revisions__lock {
  margin: 0 0 1rem;
  padding: 0.625rem 0.75rem;
  border-left: 3px solid var(--border-plain-warning);
  background: var(--background-contrast-warning);
  font-size: 0.875rem;
}

.revisions__actions {
  margin-bottom: 0.75rem;
}

.revisions__item-actions {
  flex-shrink: 0;
  display: flex;
  gap: 0.5rem;
}

.revisions__replace {
  margin-bottom: 1rem;
}

.revisions__replace-button {
  position: relative;
  cursor: pointer;
}

.revisions__replace-button--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.revisions__file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: inherit;
}

.revisions__hint {
  margin: 0.5rem 0 0;
}

.revisions__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.revisions__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.revisions__item-main {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.25rem 0.625rem;
}

.revisions__number {
  font-weight: 600;
  font-size: 0.875rem;
}

.revisions__badge {
  padding: 0 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-contrast-success);
  color: var(--text-default-success);
  font-size: 0.75rem;
}

.revisions__origin {
  font-size: 0.8125rem;
}

.revisions__meta {
  flex-basis: 100%;
  overflow-wrap: anywhere;
}
</style>
