<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const { runEvaluation } = useCollections()

const evaluationRuns = computed(() => props.collection.evaluationRuns)
const { page, pageCount, paged: pagedRuns } = usePagination(evaluationRuns)

const expandedRunId = ref<string>()

const validatedCount = computed(() => props.collection.qaPairs.filter((pair) => pair.validated).length)

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}

function toggleExpand(runId: string) {
  expandedRunId.value = expandedRunId.value === runId ? undefined : runId
}

const METRIC_LABELS = [
  { key: 'precisionAtK', label: 'Precision@k' },
  { key: 'recallAtK', label: 'Recall@k' },
  { key: 'mrr', label: 'MRR' },
  { key: 'ndcg', label: 'NDCG' },
] as const

const STRATEGY_LABEL: Record<string, string> = {
  paragraph: 'Par paragraphe',
  fixed: 'Taille fixe',
  semantic: 'Sémantique',
  llm: 'Par LLM',
}
</script>

<template>
  <div>
    <p class="eval-tab__intro">
      Mesure la qualité du retrieval en interrogeant le pipeline avec les questions de référence, puis en
      comparant les chunks remontés à la source attendue de chaque Q/R.
    </p>

    <div class="eval-tab__launch">
      <span class="eval-tab__count">
        {{ validatedCount }} question(s)-réponse(s) validée(s) sur {{ collection.qaPairs.length }} —
        seules les paires validées sont utilisées.
      </span>
      <button
        type="button"
        class="fr-btn"
        :disabled="validatedCount === 0"
        @click="runEvaluation(collection.id)"
      >
        Lancer l'évaluation
      </button>
    </div>

    <ul v-if="collection.evaluationRuns.length" class="eval-tab__runs">
      <li v-for="run in pagedRuns" :key="run.id" class="eval-tab__run">
        <button type="button" class="eval-tab__run-header" @click="toggleExpand(run.id)">
          <span class="eval-tab__run-header-text">
            <span class="eval-tab__run-date">{{ formatDate(run.runAt) }} · {{ run.pairCount }} paire(s) · k={{ run.k }}</span>
            <span class="eval-tab__run-config">
              {{ STRATEGY_LABEL[run.chunkingSnapshot.strategy] }}
              <template v-if="run.chunkingSnapshot.strategy === 'paragraph' || run.chunkingSnapshot.strategy === 'fixed'">
                ({{ run.chunkingSnapshot.chunkSize }} tokens, chevauchement {{ run.chunkingSnapshot.chunkOverlap }})
              </template>
              · embedding {{ run.chunkingSnapshot.embeddingModel }} · LLM {{ run.llmModel }}
            </span>
          </span>
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            :style="{ transform: expandedRunId === run.id ? 'rotate(180deg)' : 'none' }"
            aria-hidden="true"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>

        <div class="eval-tab__metrics">
          <div v-for="metric in METRIC_LABELS" :key="metric.key" class="eval-tab__metric">
            <span class="eval-tab__metric-value">{{ run.metrics[metric.key].toFixed(2) }}</span>
            <span class="eval-tab__metric-label">{{ metric.label }}</span>
          </div>
        </div>

        <div v-if="expandedRunId === run.id" class="eval-tab__results">
          <div v-for="result in run.results" :key="result.qaPairId" class="eval-tab__result">
            <p class="eval-tab__result-question">{{ result.question }}</p>

            <div class="eval-tab__result-answers">
              <div>
                <span class="eval-tab__label">Réponse attendue</span>
                <p>{{ result.expectedAnswer }}</p>
              </div>
              <div>
                <span class="eval-tab__label">Réponse générée</span>
                <p>{{ result.generatedAnswer }}</p>
              </div>
            </div>

            <div class="eval-tab__result-sources">
              <span class="eval-tab__label">Sources récupérées</span>
              <span v-for="source in result.retrievedSources" :key="source" class="eval-tab__chip">
                {{ source }}
              </span>
            </div>

            <div class="eval-tab__result-metrics">
              <span>Precision@k {{ result.precisionAtK.toFixed(2) }}</span>
              <span>Recall@k {{ result.recallAtK.toFixed(2) }}</span>
              <span>RR {{ result.reciprocalRank.toFixed(2) }}</span>
              <span>NDCG {{ result.ndcg.toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </li>
    </ul>
    <p v-else class="eval-tab__empty">Aucune évaluation lancée pour le moment.</p>

    <PaginationControls v-model:page="page" :page-count="pageCount" />
  </div>
</template>

<style scoped>
.eval-tab__intro {
  margin: 0 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.eval-tab__launch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  margin-bottom: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.eval-tab__count {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.eval-tab__runs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.eval-tab__run {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  padding: 0.875rem;
}

.eval-tab__run-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  width: 100%;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  color: var(--text-default-grey);
  text-align: left;
}

.eval-tab__run-header svg {
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.eval-tab__run-header-text {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.eval-tab__run-date {
  font-size: 0.8125rem;
  font-weight: 700;
}

.eval-tab__run-config {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.eval-tab__metrics {
  display: flex;
  gap: 1.5rem;
  margin-top: 0.75rem;
}

.eval-tab__metric {
  display: flex;
  flex-direction: column;
}

.eval-tab__metric-value {
  font-size: 1.25rem;
  font-weight: 700;
}

.eval-tab__metric-label {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.eval-tab__results {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

.eval-tab__result {
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
  font-size: 0.8125rem;
}

.eval-tab__result-question {
  margin: 0 0 0.5rem;
  font-weight: 700;
}

.eval-tab__label {
  display: block;
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--text-mention-grey);
  margin-bottom: 0.125rem;
}

.eval-tab__result-answers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.eval-tab__result-answers p {
  margin: 0;
}

.eval-tab__result-sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.625rem;
}

.eval-tab__chip {
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  font-size: 0.75rem;
}

.eval-tab__result-metrics {
  display: flex;
  gap: 1rem;
  margin-top: 0.625rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-default-grey);
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.eval-tab__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}
</style>
