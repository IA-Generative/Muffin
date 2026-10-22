<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { usePagination } from '../composables/usePagination'
import type { Collection, EvaluationResult } from '../types/collection'
import PaginationControls from './PaginationControls.vue'

const props = defineProps<{
  collection: Collection
}>()

const { runEvaluation, isEvaluating, deleteEvaluation, loadTabData, fetchEvaluationResults } = useCollections()

// The counts below come from the QA pairs, which are otherwise only loaded by their own tab.
onMounted(() => loadTabData(props.collection.id, 'qa'))

const evaluationRuns = computed(() => props.collection.evaluationRuns)
const { page, pageCount, paged: pagedRuns } = usePagination(evaluationRuns)

const evaluating = computed(() => isEvaluating(props.collection.id))

const expandedRunId = ref<string>()
// Per-pair results are not part of the list response: loaded the first time a run is
// expanded, then cached - expanding again must not refetch.
const resultsByRunId = ref<Record<string, EvaluationResult[]>>({})
const loadingRunId = ref<string>()

async function toggleExpand(runId: string) {
  if (expandedRunId.value === runId) {
    expandedRunId.value = undefined
    return
  }
  expandedRunId.value = runId
  if (resultsByRunId.value[runId]) return
  loadingRunId.value = runId
  try {
    resultsByRunId.value[runId] = await fetchEvaluationResults(props.collection.id, runId)
  } finally {
    loadingRunId.value = undefined
  }
}

// The run's promptfoo report, served by the backend (every access is checked) and
// displayed in a fully sandboxed iframe: the HTML comes from promptfoo, so it gets no
// scripts, no same-origin rights, nothing.
const reportRunId = ref<string>()
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const reportUrl = computed(() =>
  reportRunId.value
    ? `${API_BASE_URL}/api/collections/${props.collection.id}/evaluations/${reportRunId.value}/report`
    : '',
)

const evaluableCount = computed(() => props.collection.qaPairs.filter((pair) => pair.source).length)
const skippedCount = computed(() => props.collection.qaPairs.length - evaluableCount.value)

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}

function formatFactuality(value: number) {
  return value.toFixed(2)
}

const STRATEGY_LABEL: Record<string, string> = {
  paragraph: 'Par paragraphe',
  fixed: 'Taille fixe',
  semantic: 'Sémantique',
  llm: 'Par LLM',
}

const EVAL_K = 5

// Below this many test questions a score moves a lot with a single question: shown next to it.
const GOLDEN_RELIABLE_COUNT = 30
const goldenCount = computed(() => props.collection.qaPairs.filter((pair) => pair.golden).length)
</script>

<template>
  <div>
    <p class="eval-tab__intro">
      Mesure la qualité des réponses générées : chaque question-réponse de la collection est posée au pipeline, puis un
      juge (modèle d'évaluation) note la factualité de la réponse générée face à la réponse attendue.
    </p>
    <p class="eval-tab__intro">
      Les <strong>questions de test</strong> ({{ goldenCount }}) sont écrites par une personne et ne sont dans aucun
      index : leurs scores sont présentés à part, et ce sont ceux à suivre dans le temps. Les questions générées
      viennent du texte même des documents, leurs scores sont plus flatteurs.
    </p>

    <div class="eval-tab__launch">
      <span class="eval-tab__count">
        {{ evaluableCount }} question(s)-réponse(s) évaluable(s) (avec document source) sur {{ collection.qaPairs.length }}
        <template v-if="skippedCount > 0"> — {{ skippedCount }} sans source (non évaluables)</template>
      </span>
      <button
        type="button"
        class="fr-btn"
        :disabled="evaluableCount === 0 || evaluating"
        @click="runEvaluation(collection.id)"
      >
        {{ evaluating ? 'Évaluation en cours…' : 'Lancer l\'évaluation' }}
      </button>
    </div>

    <div v-if="evaluating" class="eval-tab__progress-card">
      <div class="eval-tab__progress-spinner" aria-hidden="true" />
      <div class="eval-tab__progress-text">
        <span class="eval-tab__progress-title">Évaluation en cours…</span>
        <span class="eval-tab__progress-detail">
          {{ evaluableCount }} question(s) en cours d'évaluation · k={{ EVAL_K }}
        </span>
      </div>
    </div>

    <ul v-if="collection.evaluationRuns.length" class="eval-tab__runs">
      <li v-for="run in pagedRuns" :key="run.id" class="eval-tab__run">
        <div class="eval-tab__run-header">
          <button type="button" class="eval-tab__run-toggle" @click="toggleExpand(run.id)">
            <span class="eval-tab__run-header-text">
              <span class="eval-tab__run-date">{{ formatDate(run.runAt) }} · {{ run.pairCount }} paire(s) · k={{ run.k }}</span>
              <span class="eval-tab__run-config">
                {{ STRATEGY_LABEL[run.chunkingSnapshot.strategy] }}
                <template v-if="run.chunkingSnapshot.strategy === 'paragraph' || run.chunkingSnapshot.strategy === 'fixed'">
                  ({{ run.chunkingSnapshot.chunkSize }} tokens, chevauchement {{ run.chunkingSnapshot.chunkOverlap }})
                </template>
                · embedding {{ run.chunkingSnapshot.embeddingModel }} · juge {{ run.llmModel }}
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
          <button
            type="button"
            class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm eval-tab__delete-btn"
            title="Supprimer cette évaluation"
            @click="deleteEvaluation(collection.id, run.id)"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div v-if="run.goldenMetrics" class="eval-tab__group eval-tab__group--golden">
          <p class="eval-tab__group-title">
            Questions de test
            <span class="eval-tab__group-count">{{ run.goldenPairCount }} question(s)</span>
          </p>
          <div class="eval-tab__metrics">
            <div class="eval-tab__metric">
              <span class="eval-tab__metric-value">{{ formatFactuality(run.goldenMetrics.factuality) }}</span>
              <span class="eval-tab__metric-label">Factualité (juge)</span>
            </div>
          </div>
          <p v-if="run.goldenPairCount < GOLDEN_RELIABLE_COUNT" class="eval-tab__group-note">
            Seulement {{ run.goldenPairCount }} question(s) : une variation de score d'un test à l'autre peut
            n'être que du bruit.
          </p>
        </div>

        <div v-if="run.metrics" class="eval-tab__group">
          <p class="eval-tab__group-title">
            Questions générées et de référence
            <span class="eval-tab__group-count">
              {{ run.validatedPairCount }} validée(s) · {{ run.unvalidatedPairCount }} non validée(s)
            </span>
          </p>
          <div class="eval-tab__metrics">
            <div class="eval-tab__metric">
              <span class="eval-tab__metric-value">{{ formatFactuality(run.metrics.factuality) }}</span>
              <span class="eval-tab__metric-label">Factualité (juge)</span>
            </div>
          </div>
        </div>

        <div v-if="run.hasArtifacts" class="eval-tab__artifacts">
          <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="reportRunId = run.id">
            Voir le rapport
          </button>
          <a
            class="fr-link fr-link--download"
            :href="`${API_BASE_URL}/api/collections/${collection.id}/evaluations/${run.id}/report?download=1`"
            download
          >
            Rapport HTML
          </a>
          <a
            class="fr-link fr-link--download"
            :href="`${API_BASE_URL}/api/collections/${collection.id}/evaluations/${run.id}/results.json`"
            download
          >
            results.json
          </a>
        </div>

        <div v-if="expandedRunId === run.id" class="eval-tab__results">
          <p v-if="loadingRunId === run.id" class="eval-tab__empty">Chargement des résultats…</p>
          <template v-else>
            <div v-for="result in resultsByRunId[run.id]" :key="result.qaPairId" class="eval-tab__result">
              <p class="eval-tab__result-question">
                <span v-if="result.golden" class="eval-tab__badge">Test</span>
                <span v-else-if="result.validated" class="eval-tab__badge eval-tab__badge--validated">Validée</span>
                {{ result.question }}
              </p>

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
                <span v-if="result.factuality !== null">Factualité {{ formatFactuality(result.factuality) }}</span>
                <span v-else class="eval-tab__judge-error">Juge en erreur sur cette paire</span>
              </div>
            </div>
            <p v-if="!resultsByRunId[run.id]?.length" class="eval-tab__empty">
              Aucun résultat détaillé pour cette évaluation.
            </p>
          </template>
        </div>
      </li>
    </ul>
    <p v-else class="eval-tab__empty">Aucune évaluation lancée pour le moment.</p>

    <PaginationControls v-model:page="page" :page-count="pageCount" />

    <div v-if="reportRunId" class="eval-tab__modal-overlay" @click.self="reportRunId = undefined">
      <div class="eval-tab__modal">
        <div class="eval-tab__modal-header">
          <p class="eval-tab__modal-title">Rapport d'évaluation</p>
          <button
            type="button"
            class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm"
            title="Fermer le rapport"
            @click="reportRunId = undefined"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <!-- Fully sandboxed: the report is promptfoo-generated HTML, it gets no scripts
             and no same-origin rights - it is only meant to be read. -->
        <iframe :src="reportUrl" class="eval-tab__modal-frame" sandbox="" title="Rapport d'évaluation" />
      </div>
    </div>
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
  gap: 0.5rem;
  width: 100%;
}

.eval-tab__run-toggle {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  flex: 1;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
  color: var(--text-default-grey);
  text-align: left;
}

.eval-tab__run-toggle svg {
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.eval-tab__delete-btn {
  flex-shrink: 0;
  margin-top: -0.125rem;
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

.eval-tab__group {
  margin-top: 0.75rem;
}

.eval-tab__group--golden {
  padding: 0.625rem 0.875rem;
  border-left: 3px solid var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  border-radius: 0.25rem;
}

.eval-tab__group-title {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 700;
}

.eval-tab__group-count {
  margin-left: 0.5rem;
  font-weight: 400;
  color: var(--text-mention-grey);
}

.eval-tab__group-note {
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.eval-tab__badge {
  margin-right: 0.375rem;
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
  font-size: 0.6875rem;
  font-weight: 700;
}

.eval-tab__badge--validated {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.eval-tab__metrics {
  display: flex;
  gap: 1.5rem;
  margin-top: 0.375rem;
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

.eval-tab__artifacts {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-top: 0.75rem;
  font-size: 0.8125rem;
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

.eval-tab__result-sources .eval-tab__label {
  margin-bottom: 0;
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

.eval-tab__judge-error {
  color: var(--text-default-warning);
}

.eval-tab__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.eval-tab__progress-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
  margin-bottom: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
}

.eval-tab__progress-spinner {
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--border-default-grey);
  border-top-color: var(--text-action-high-blue-france);
  border-radius: 50%;
  animation: eval-tab-spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes eval-tab-spin {
  to {
    transform: rotate(360deg);
  }
}

.eval-tab__progress-text {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.eval-tab__progress-title {
  font-weight: 700;
  font-size: 0.875rem;
}

.eval-tab__progress-detail {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.eval-tab__modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  background: rgba(0, 0, 0, 0.5);
}

.eval-tab__modal {
  display: flex;
  flex-direction: column;
  width: min(56rem, 100%);
  height: min(48rem, 100%);
  background: var(--background-default-grey);
  border-radius: 0.5rem;
  overflow: hidden;
}

.eval-tab__modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.eval-tab__modal-title {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 700;
}

.eval-tab__modal-frame {
  flex: 1;
  width: 100%;
  border: none;
}
</style>
