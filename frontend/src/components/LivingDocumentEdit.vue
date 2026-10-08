<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { DraftError, useDocumentDraft, type DocumentDraft } from '../composables/useDocumentDraft'
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

const api = useDocumentDraft()

const draft = ref<DocumentDraft | null>(null)
const loaded = ref(false)
const prompt = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const reviewing = ref(false)

const isPending = computed(() => draft.value?.status === 'pending')

function message(failure: unknown): string {
  return failure instanceof DraftError ? failure.message : 'L’opération a échoué.'
}

async function load() {
  try {
    draft.value = await api.fetchDraft(props.collectionId, props.documentId)
  } catch {
    // A failed poll is retried on the next tick - the draft itself is unaffected.
  }
  loaded.value = true
}

// Poll fast while a job runs, slowly otherwise: reading the draft is also what keeps it (and the
// document lock it holds) from lapsing while this panel is open.
let timer: ReturnType<typeof setTimeout> | undefined
function schedule() {
  timer = setTimeout(async () => {
    await load()
    schedule()
  }, isPending.value ? 2000 : 10_000)
}

onMounted(async () => {
  await load()
  schedule()
})
onUnmounted(() => clearTimeout(timer))

watch(
  draft,
  (now, before) => {
    emit('hasDraft', now !== null)
    // The job the user started just finished: bring the result up without making them look for it.
    if (before?.status === 'pending' && now && now.status !== 'pending') reviewing.value = true
    if (!now) reviewing.value = false
  },
)

// Runs an action on the draft; the result (a new draft state) replaces the current one.
async function run(action: () => Promise<DocumentDraft | void>) {
  busy.value = true
  error.value = null
  try {
    const result = await action()
    if (result) draft.value = result
  } catch (failure) {
    error.value = message(failure)
    await load() // the draft may have lapsed or moved on: show what is true now
  } finally {
    busy.value = false
  }
}

async function request() {
  const text = prompt.value.trim()
  if (!text || busy.value) return
  await run(async () => {
    const created = await api.createDraft(props.collectionId, props.documentId, text)
    prompt.value = ''
    reviewing.value = true
    return created
  })
}

const adjust = (text: string) => run(() => api.adjustDraft(props.collectionId, props.documentId, text))
const upload = (imageId: string, file: File) =>
  run(() => api.uploadImage(props.collectionId, props.documentId, imageId, file))
const insertImages = () => run(() => api.insertImages(props.collectionId, props.documentId))

async function refuse() {
  await run(async () => {
    await api.refuseDraft(props.collectionId, props.documentId)
    draft.value = null
    reviewing.value = false
  })
}

async function validate() {
  await run(async () => {
    await api.validateDraft(props.collectionId, props.documentId)
    draft.value = null
    reviewing.value = false
    emit('changed')
  })
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

    <form v-if="!draft" class="edit__form" @submit.prevent="request">
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
