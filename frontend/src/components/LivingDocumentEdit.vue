<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import { useDraftSession } from '../composables/useDraftSession'
import type { DocumentDraft } from '../composables/useDocumentDraft'
import DraftReviewModal from './DraftReviewModal.vue'

const props = defineProps<{
  collectionId: string
  documentId: string
  // Only the collection owner can ask for an edit - same gating as every other write in the UI.
  editable: boolean
}>()

const emit = defineEmits<{
  // The edit was validated: the document has a new revision and is being reindexed.
  changed: []
  // Whether the document currently has a proposed edit (it holds the document's lock, which the
  // revisions panel would otherwise describe as "another session").
  hasDraft: [value: boolean]
}>()

const { draft, loaded, busy, error, reviewing, request, adjust, upload, insertImages, refuse, validate } =
  useDraftSession(toRef(props, 'collectionId'), toRef(props, 'documentId'), { onValidated: () => emit('changed') })

const prompt = ref('')
const isPending = computed(() => draft.value?.status === 'pending')

watch(draft, (now) => emit('hasDraft', now !== null))

async function submit() {
  const text = prompt.value.trim()
  if (!text || busy.value) return
  await request(text)
  if (!error.value) prompt.value = ''
}

const STATUS_LABEL: Record<DocumentDraft['status'], string> = {
  pending: 'En cours…',
  ready: 'Prête à être examinée',
  failed: 'Échec',
}
</script>

<template>
  <section v-if="editable && loaded" class="edit">
    <h3 class="edit__title">Modifier avec l’agent</h3>

    <form v-if="!draft" class="edit__form" @submit.prevent="submit">
      <label for="edit-prompt" class="edit__hint">
        Décrivez la modification à faire. L’agent prépare une proposition : vous la relisez avant qu’elle soit
        enregistrée.
      </label>
      <textarea
        id="edit-prompt"
        v-model="prompt"
        class="edit__textarea"
        rows="3"
        maxlength="4000"
        placeholder="Par exemple : ajoute le numéro d’urgence dans la section Contacts"
        :disabled="busy"
      />
      <button type="submit" class="fr-btn" :disabled="!prompt.trim() || busy">Proposer une modification</button>
    </form>

    <div v-else class="edit__card">
      <p class="edit__prompt">« {{ draft.prompt }} »</p>
      <p class="edit__status" :class="`edit__status--${draft.status}`" role="status">
        <span v-if="isPending" class="edit__spinner" aria-hidden="true" />
        {{ STATUS_LABEL[draft.status] }}
        <template v-if="draft.status === 'ready' && !draft.edited"> - l’agent n’a rien modifié</template>
      </p>
      <p v-if="draft.status === 'failed' && draft.error" class="edit__error" role="alert">{{ draft.error }}</p>
      <div class="edit__actions">
        <button type="button" class="fr-btn fr-btn--sm" @click="reviewing = true">
          {{ draft.status === 'ready' && draft.edited ? 'Examiner la modification' : 'Ouvrir' }}
        </button>
        <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" :disabled="busy" @click="refuse">
          Abandonner
        </button>
      </div>
    </div>

    <p v-if="error && !reviewing" class="edit__error" role="alert">{{ error }}</p>

    <DraftReviewModal
      v-if="draft && reviewing"
      :collection-id="collectionId"
      :document-id="documentId"
      :draft="draft"
      :busy="busy"
      :error="error"
      @close="reviewing = false"
      @adjust="adjust"
      @validate="validate"
      @refuse="refuse"
      @upload="upload"
      @insert-images="insertImages"
    />
  </section>
</template>

<style scoped>
.edit {
  margin-bottom: 1.25rem;
  padding: 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.edit__title {
  margin: 0 0 0.5rem;
  font-size: 0.9375rem;
}

.edit__hint {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.edit__textarea {
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  resize: vertical;
}

.edit__prompt {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  font-style: italic;
}

.edit__status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.edit__status--ready {
  color: var(--text-default-success);
}

.edit__status--failed,
.edit__error {
  color: var(--text-default-error);
}

.edit__error {
  margin: 0 0 0.75rem;
  font-size: 0.8125rem;
}

.edit__actions {
  display: flex;
  gap: 0.5rem;
}

.edit__spinner {
  width: 0.875rem;
  height: 0.875rem;
  border: 2px solid var(--border-default-grey);
  border-top-color: var(--border-action-high-blue-france);
  border-radius: 50%;
  animation: edit-spin 0.8s linear infinite;
}

@keyframes edit-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .edit__spinner {
    animation: none;
  }
}
</style>
