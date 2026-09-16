<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const { addQaPair, removeQaPair, toggleQaValidation } = useCollections()

const qaPairs = computed(() => props.collection.qaPairs)
const { page, pageCount, paged: pagedQaPairs } = usePagination(qaPairs)

const questionDraft = ref('')
const answerDraft = ref('')

function submit() {
  addQaPair(props.collection.id, questionDraft.value, answerDraft.value)
  questionDraft.value = ''
  answerDraft.value = ''
}
</script>

<template>
  <div>
    <p class="qa-tab__intro">
      Ajoutez des questions-réponses de référence : l'assistant les utilisera en priorité avant de chercher
      dans les documents.
    </p>

    <form class="qa-tab__form" @submit.prevent="submit">
      <input v-model="questionDraft" type="text" placeholder="Question" aria-label="Nouvelle question" />
      <textarea v-model="answerDraft" rows="2" placeholder="Réponse" aria-label="Réponse associée" />
      <button type="submit" class="fr-btn fr-btn--secondary" :disabled="!questionDraft.trim() || !answerDraft.trim()">
        Ajouter
      </button>
    </form>

    <ul v-if="collection.qaPairs.length" class="qa-tab__list">
      <li v-for="pair in pagedQaPairs" :key="pair.id" class="qa-tab__item">
        <div class="qa-tab__item-body">
          <div class="qa-tab__item-tags">
            <span class="qa-tab__origin" :class="`qa-tab__origin--${pair.origin}`">
              {{ pair.origin === 'manual' ? 'Manuel' : 'Généré' }}
            </span>
            <span v-if="pair.source" class="qa-tab__source">{{ pair.source }}</span>
          </div>
          <span class="qa-tab__question">{{ pair.question }}</span>
          <span class="qa-tab__answer">{{ pair.answer }}</span>
        </div>

        <button
          type="button"
          class="qa-tab__validate"
          :class="{ 'qa-tab__validate--active': pair.validated }"
          @click="toggleQaValidation(collection.id, pair.id)"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
          </svg>
          {{ pair.validated ? 'Validé' : 'À valider' }}
        </button>

        <button
          type="button"
          class="qa-tab__remove"
          :aria-label="`Retirer la question ${pair.question}`"
          @click="removeQaPair(collection.id, pair.id)"
        >
          ✕
        </button>
      </li>
    </ul>
    <p v-else class="qa-tab__empty">Aucune question-réponse pour le moment.</p>

    <PaginationControls v-model:page="page" :page-count="pageCount" />
  </div>
</template>

<style scoped>
.qa-tab__intro {
  margin: 0 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.qa-tab__form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.qa-tab__form input,
.qa-tab__form textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  box-sizing: border-box;
  resize: vertical;
}

.qa-tab__form button {
  align-self: flex-end;
}

.qa-tab__list {
  list-style: none;
  margin: 1.25rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.qa-tab__item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.qa-tab__item-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.qa-tab__item-tags {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.125rem;
}

.qa-tab__origin {
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.qa-tab__origin--manual {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.qa-tab__source {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.qa-tab__validate {
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

.qa-tab__validate--active {
  border-color: var(--border-action-high-success);
  background: var(--background-alt-green-emeraude);
  color: var(--text-default-success);
}

.qa-tab__question {
  font-weight: 700;
  font-size: 0.875rem;
}

.qa-tab__answer {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.qa-tab__remove {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.qa-tab__empty {
  margin-top: 1.25rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}
</style>
