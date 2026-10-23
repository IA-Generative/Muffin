<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection, QaPair } from '../types/collection'
import PaginationControls from './PaginationControls.vue'
import SourceDocumentModal from './SourceDocumentModal.vue'

const props = defineProps<{
  collection: Collection
}>()

const { addQaPair, removeQaPair, toggleQaValidation, qaError, loadTabData } = useCollections()

// The documents a test question can point at: loaded here too, since this tab may be opened first.
onMounted(() => loadTabData(props.collection.id, 'documents'))

// The pair whose source is open (#349): its document on the page the answer comes from, the passage highlighted.
const openSource = ref<QaPair>()

function hasPassage(pair: QaPair): boolean {
  return !!pair.sourceDocumentId && !!pair.sourcePage && !!pair.sourceExcerpt
}

const qaPairs = computed(() => props.collection.qaPairs)
const { page, pageCount, paged: pagedQaPairs } = usePagination(qaPairs)

const questionDraft = ref('')
const answerDraft = ref('')
// A test (golden) question, instead of a reference the assistant answers from.
const golden = ref(false)
const relevantDocumentIds = ref<string[]>([])

const goldenCount = computed(() => props.collection.qaPairs.filter((pair) => pair.golden).length)
// A test question is scored against the documents that hold its answer: without one it can't be.
const canSubmit = computed(
  () =>
    !!questionDraft.value.trim() &&
    !!answerDraft.value.trim() &&
    (!golden.value || relevantDocumentIds.value.length > 0),
)

async function submit() {
  const saved = await addQaPair(props.collection.id, questionDraft.value, answerDraft.value, {
    golden: golden.value,
    relevantDocumentIds: golden.value ? relevantDocumentIds.value : [],
  })
  if (!saved) return
  questionDraft.value = ''
  answerDraft.value = ''
  relevantDocumentIds.value = []
}
</script>

<template>
  <div>
    <p class="qa-tab__intro">
      <strong>Questions de référence</strong> : l'assistant les utilise en priorité avant de chercher dans les
      documents.<br />
      <strong>Questions de test</strong> : écrites par une personne, jamais utilisées pour répondre. Elles servent
      uniquement à mesurer la qualité de la recherche (Avancé › Évaluation), sur des questions qui ne viennent pas du
      texte des documents.
    </p>

    <form class="qa-tab__form" @submit.prevent="submit">
      <input v-model="questionDraft" type="text" placeholder="Question" aria-label="Nouvelle question" />
      <textarea v-model="answerDraft" rows="2" placeholder="Réponse" aria-label="Réponse associée" />

      <label class="qa-tab__golden">
        <input v-model="golden" type="checkbox" />
        <span>
          Question de test
          <span class="qa-tab__hint">Jamais utilisée pour répondre : sert uniquement à l'évaluation.</span>
        </span>
      </label>

      <fieldset v-if="golden" class="qa-tab__documents">
        <legend>Documents qui contiennent la réponse</legend>
        <p v-if="collection.documents.length === 0" class="qa-tab__hint">
          Ajoutez d'abord des documents à la collection : une question de test est évaluée par rapport à eux.
        </p>
        <label v-for="document in collection.documents" :key="document.id" class="qa-tab__document">
          <input v-model="relevantDocumentIds" type="checkbox" :value="document.id" />
          {{ document.name }}
        </label>
        <p v-if="collection.documents.length" class="qa-tab__hint">
          Au moins un : sans document, la question ne peut pas être évaluée.
        </p>
      </fieldset>

      <p v-if="qaError" class="qa-tab__error" role="alert">{{ qaError }}</p>
      <button type="submit" class="fr-btn fr-btn--secondary" :disabled="!canSubmit">
        {{ golden ? 'Ajouter la question de test' : 'Ajouter' }}
      </button>
    </form>

    <p v-if="goldenCount" class="qa-tab__summary">
      {{ goldenCount }} question{{ goldenCount > 1 ? 's' : '' }} de test sur {{ collection.qaPairs.length }}
      <template v-if="goldenCount < 30">
        - avec si peu de questions, les scores de l'évaluation varient beaucoup d'un test à l'autre.
      </template>
    </p>

    <ul v-if="collection.qaPairs.length" class="qa-tab__list">
      <li v-for="pair in pagedQaPairs" :key="pair.id" class="qa-tab__item">
        <div class="qa-tab__item-body">
          <div class="qa-tab__item-tags">
            <span v-if="pair.golden" class="qa-tab__origin qa-tab__origin--golden">Test</span>
            <span v-else class="qa-tab__origin" :class="`qa-tab__origin--${pair.origin}`">
              {{ pair.origin === 'manual' ? 'Manuel' : 'Généré' }}
            </span>
            <span v-if="pair.golden && pair.relevantDocuments.length" class="qa-tab__source">
              {{ pair.relevantDocuments.map((document) => document.name).join(', ') }}
            </span>
            <button
              v-else-if="pair.source && hasPassage(pair)"
              type="button"
              class="qa-tab__source qa-tab__source--link"
              :aria-label="`Voir la source de cette réponse dans ${pair.source}, page ${pair.sourcePage}`"
              @click="openSource = pair"
            >
              {{ pair.source }} · page {{ pair.sourcePage }}
            </button>
            <span v-else-if="pair.source" class="qa-tab__source">{{ pair.source }}</span>
            <span v-else-if="pair.golden" class="qa-tab__source">Aucun document : non évaluable</span>
          </div>
          <span class="qa-tab__question">{{ pair.question }}</span>
          <span class="qa-tab__answer">{{ pair.answer }}</span>
        </div>

        <span v-if="pair.golden" class="qa-tab__validate qa-tab__validate--active qa-tab__validate--fixed">
          Toujours validée
        </span>
        <button
          v-else
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

    <SourceDocumentModal
      v-if="openSource && openSource.sourceDocumentId"
      :collection-id="collection.id"
      :document-id="openSource.sourceDocumentId"
      :document-name="openSource.source ?? ''"
      :page-number="openSource.sourcePage"
      :excerpt="openSource.sourceExcerpt"
      :start="openSource.sourceStart"
      :end="openSource.sourceEnd"
      @close="openSource = undefined"
    />
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

.qa-tab__origin--golden {
  background: var(--background-alt-purple-glycine, var(--background-alt-blue-france));
  color: var(--text-default-info, var(--text-action-high-blue-france));
}

.qa-tab__origin--manual {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.qa-tab__source {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.qa-tab__source--link {
  padding: 0;
  border: none;
  background: transparent;
  font: inherit;
  color: var(--text-action-high-blue-france);
  text-decoration: underline;
  cursor: pointer;
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

.qa-tab__validate--fixed {
  cursor: default;
}

.qa-tab__golden {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.qa-tab__golden input,
.qa-tab__document input {
  width: auto;
  margin-top: 0.25rem;
}

.qa-tab__hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.qa-tab__documents {
  margin: 0;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  max-height: 10rem;
  overflow-y: auto;
}

.qa-tab__documents legend {
  padding: 0 0.25rem;
  font-size: 0.8125rem;
  font-weight: 700;
}

.qa-tab__document {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.qa-tab__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.qa-tab__summary {
  margin: 0.75rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
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
