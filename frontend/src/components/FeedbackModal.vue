<script setup lang="ts">
import { ref, watch } from 'vue'
import type { FeedbackDetails, Source } from '../types/chat'

const props = defineProps<{
  sources?: Source[]
  initialDetails?: FeedbackDetails | null
}>()

const emit = defineEmits<{
  close: []
  submit: [details: FeedbackDetails]
}>()

// `code` is what the backend's FeedbackReasonCode enum expects (backend/app/models/feedback.py) -
// `label` is only ever for display, never sent.
const REASONS = [
  { code: 'incorrect_answer', label: 'Réponse incorrecte' },
  { code: 'not_useful', label: 'Pas utile' },
  { code: 'questionable_sources', label: 'Sources douteuses' },
  { code: 'inappropriate_tone', label: 'Ton inapproprié' },
  { code: 'other', label: 'Autre' },
]

const selectedReasons = ref<string[]>(props.initialDetails?.reasons ?? [])
const comment = ref(props.initialDetails?.comment ?? '')
const validatedSourceIds = ref<string[]>(props.initialDetails?.validatedSourceIds ?? [])
const addedSources = ref<Source[]>(props.initialDetails?.addedSources ?? [])
const newSourceTitle = ref('')
const newSourceUrl = ref('')

// Reset fields when initialDetails changes (e.g. reopening the modal for a different message)
watch(() => props.initialDetails, (details) => {
  selectedReasons.value = details?.reasons ?? []
  comment.value = details?.comment ?? ''
  validatedSourceIds.value = details?.validatedSourceIds ?? []
  addedSources.value = details?.addedSources ?? []
})

function toggleReason(code: string) {
  const index = selectedReasons.value.indexOf(code)
  if (index === -1) selectedReasons.value.push(code)
  else selectedReasons.value.splice(index, 1)
}

function toggleValidated(sourceId: string) {
  const index = validatedSourceIds.value.indexOf(sourceId)
  if (index === -1) validatedSourceIds.value.push(sourceId)
  else validatedSourceIds.value.splice(index, 1)
}

function addSource() {
  const title = newSourceTitle.value.trim()
  const url = newSourceUrl.value.trim()
  if (!title || !url) return
  addedSources.value.push({ title, url })
  newSourceTitle.value = ''
  newSourceUrl.value = ''
}

function removeAddedSource(identifier: string) {
  addedSources.value = addedSources.value.filter((source) => (source.url ?? source.title) !== identifier)
}

function submit() {
  emit('submit', {
    reasons: selectedReasons.value,
    comment: comment.value.trim(),
    validatedSourceIds: validatedSourceIds.value,
    addedSources: addedSources.value,
  })
}
</script>

<template>
  <div class="feedback-overlay" @click.self="emit('close')">
    <div class="feedback-modal" role="dialog" aria-modal="true" aria-labelledby="feedback-title">
      <div class="feedback-modal__header">
        <h2 id="feedback-title">Signaler un problème</h2>
        <button type="button" class="feedback-modal__close" aria-label="Fermer" @click="emit('close')">
          ✕
        </button>
      </div>

      <fieldset class="feedback-modal__field">
        <legend>Qu'est-ce qui ne va pas ?</legend>
        <div class="feedback-modal__reasons">
          <button
            v-for="reason in REASONS"
            :key="reason.code"
            type="button"
            class="feedback-modal__reason"
            :class="{ 'feedback-modal__reason--active': selectedReasons.includes(reason.code) }"
            @click="toggleReason(reason.code)"
          >
            {{ reason.label }}
          </button>
        </div>
      </fieldset>

      <div class="feedback-modal__field">
        <label for="feedback-comment">Précisions (facultatif)</label>
        <textarea
          id="feedback-comment"
          v-model="comment"
          class="feedback-modal__textarea"
          rows="3"
          placeholder="Dites-nous ce qui aurait dû être différent…"
        />
      </div>

      <div v-if="sources?.length" class="feedback-modal__field">
        <label>Sources de cette réponse</label>
        <ul class="feedback-modal__sources">
          <li v-for="source in sources" :key="source.id ?? source.url ?? source.title">
            <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
            <span v-else>{{ source.title }}</span>
            <button
              v-if="source.id"
              type="button"
              class="feedback-modal__validate"
              :class="{ 'feedback-modal__validate--active': validatedSourceIds.includes(source.id) }"
              @click="toggleValidated(source.id)"
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
              Valider
            </button>
          </li>
        </ul>
      </div>

      <div class="feedback-modal__field">
        <label>Ajouter une source</label>
        <ul v-if="addedSources.length" class="feedback-modal__sources">
          <li v-for="source in addedSources" :key="source.url ?? source.title">
            <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
            <button type="button" class="feedback-modal__remove" @click="removeAddedSource(source.url ?? source.title)">
              Retirer
            </button>
          </li>
        </ul>
        <div class="feedback-modal__add-source">
          <input
            v-model="newSourceTitle"
            type="text"
            class="feedback-modal__input"
            placeholder="Titre"
            aria-label="Titre de la nouvelle source"
          />
          <input
            v-model="newSourceUrl"
            type="url"
            class="feedback-modal__input"
            placeholder="https://…"
            aria-label="URL de la nouvelle source"
          />
          <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="addSource">
            Ajouter
          </button>
        </div>
      </div>

      <div class="feedback-modal__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="emit('close')">Annuler</button>
        <button type="button" class="fr-btn" @click="submit">Envoyer</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feedback-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.feedback-modal {
  width: 100%;
  max-width: 28rem;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.feedback-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.feedback-modal__header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.feedback-modal__close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-mention-grey);
}

.feedback-modal__field {
  border: none;
  padding: 0;
  margin: 1.25rem 0 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.feedback-modal__field legend,
.feedback-modal__field > label {
  font-size: 0.875rem;
  font-weight: 700;
  padding: 0;
}

.feedback-modal__reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.feedback-modal__reason {
  padding: 0.375rem 0.75rem;
  border-radius: 1rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.8125rem;
}

.feedback-modal__reason:hover {
  background: var(--background-alt-grey-hover);
}

.feedback-modal__reason--active {
  border-color: var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  font-weight: 700;
}

.feedback-modal__textarea {
  width: 100%;
  resize: vertical;
  padding: 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  box-sizing: border-box;
}

.feedback-modal__sources {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.feedback-modal__sources li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.feedback-modal__sources a,
.feedback-modal__sources span {
  color: var(--text-action-high-blue-france);
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feedback-modal__validate {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.625rem;
  border-radius: 1rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 0.75rem;
}

.feedback-modal__validate:hover {
  background: var(--background-alt-grey-hover);
}

.feedback-modal__validate--active {
  border-color: var(--border-action-high-success);
  background: var(--background-alt-green-emeraude);
  color: var(--text-default-success);
}

.feedback-modal__remove {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-default-error);
  cursor: pointer;
  font-size: 0.75rem;
}

.feedback-modal__add-source {
  display: flex;
  gap: 0.5rem;
}

.feedback-modal__input {
  flex: 1;
  min-width: 0;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  font-size: 0.8125rem;
}

.feedback-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}
</style>
