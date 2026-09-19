<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useQuality } from '../composables/useQuality'
import { useModels } from '../composables/useModels'

const { collections } = useCollections()
const { models } = useModels()
const {
  overview,
  isLoading,
  error,
  fetchOverview,
  scoreConversation,
  scoreAll,
  isScoring,
  isScoringAll,
  currentPage,
  pageSize,
} = useQuality()

const selectedCollectionId = ref<'all' | string>('all')
const selectedScoringModel = ref<string | null>(null)
const selectedModelFilter = ref<'all' | string>('all')

onMounted(() => {
  fetchOverview()
})

watch(selectedCollectionId, (val) => {
  fetchOverview(val === 'all' ? null : val, 1, getModelFilterParam())
})

watch(selectedModelFilter, () => {
  const cid = selectedCollectionId.value === 'all' ? null : selectedCollectionId.value
  fetchOverview(cid, 1, getModelFilterParam())
})

function getModelFilterParam(): string | null {
  return selectedModelFilter.value === 'all' ? null : selectedModelFilter.value
}

// ── Computed metrics ────────────────────────────────────────────────────────

const retrievalMetrics = computed(() => overview.value?.retrieval ?? [])
const feedback = computed(() => overview.value?.feedback)
const discussion = computed(() => overview.value?.discussion)
const groundedness = computed(() => overview.value?.groundedness)
const conversations = computed(() => overview.value?.conversations ?? [])

const conversationsTotal = computed(() => overview.value?.conversationsTotal ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(conversationsTotal.value / pageSize.value)))

const feedbackTotal = computed(() => {
  const f = feedback.value
  if (!f) return 0
  return f.upCount + f.downCount
})

const feedbackUpRatio = computed(() => {
  const f = feedback.value
  if (!f || f.upCount + f.downCount === 0) return null
  return f.upCount / (f.upCount + f.downCount)
})

const topReason = computed(() => {
  const f = feedback.value
  if (!f || !f.reasonCounts) return null
  const entries = Object.entries(f.reasonCounts)
  if (entries.length === 0) return null
  entries.sort((a, b) => b[1] - a[1])
  return { reason: entries[0][0], count: entries[0][1], total: entries.reduce((s, [, c]) => s + c, 0) }
})

const groundedRatio = computed(() => {
  const g = groundedness.value
  if (!g || g.evaluatedCount === 0) return null
  return (g.evaluatedCount - g.ungroundedCount) / g.evaluatedCount
})

const discussionCoherenceRatio = computed(() => {
  const d = discussion.value
  if (!d || d.totalConversations === 0) return null
  return d.coherentCount / d.totalConversations
})

// Conversations that still need scoring (on the current page)
const unscoredConversations = computed(() =>
  conversations.value.filter((c) => c.coherent === null)
)

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}

function pct(value: number | null): string {
  if (value === null) return '—'
  return `${Math.round(value * 100)} %`
}

function formatLatency(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

function formatCost(cost: number | null): string {
  if (cost === null) return '—'
  if (cost < 1) return `${(cost * 100).toFixed(1)} cts`
  return `${cost.toFixed(2)} €`
}

function ratio(value: number | null): string {
  if (value === null) return '—'
  return value.toFixed(2)
}

const REASON_LABELS: Record<string, string> = {
  incorrect_answer: 'Réponse incorrecte',
  not_useful: 'Pas utile',
  questionable_sources: 'Sources douteuses',
  inappropriate_tone: 'Ton inapproprié',
  other: 'Autre',
}

async function handleScoreConversation(conversationId: string) {
  await scoreConversation(conversationId, selectedScoringModel.value)
}

async function handleScoreAll() {
  const cid = selectedCollectionId.value === 'all' ? null : selectedCollectionId.value
  await scoreAll(cid, selectedScoringModel.value)
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  const cid = selectedCollectionId.value === 'all' ? null : selectedCollectionId.value
  fetchOverview(cid, page, getModelFilterParam())
}

// Expandable rows: track which conversations have their score history expanded
const expandedConversations = ref<Set<string>>(new Set())

function toggleConversationExpand(id: string) {
  if (expandedConversations.value.has(id)) {
    expandedConversations.value.delete(id)
  } else {
    expandedConversations.value.add(id)
  }
}
</script>

<template>
  <section class="quality-view">
    <div class="quality-view__header">
      <h1>Qualité</h1>
      <p class="quality-view__intro">
        Vue d'ensemble des métriques de qualité de l'agent — retrieval, retours utilisateur, cohérence de
        discussion, et groundedness. Les administrateurs voient toutes les collections et toutes les
        conversations agrégées.
      </p>

      <div class="quality-view__scope">
        <div class="quality-view__scope-field">
          <label for="quality-collection-picker">Collection</label>
          <select id="quality-collection-picker" v-model="selectedCollectionId" class="fr-select">
            <option value="all">Toutes les collections</option>
            <option v-for="collection in collections" :key="collection.id" :value="collection.id">
              {{ collection.name }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <div v-if="isLoading && !overview" class="quality-view__loading">
      <p>Chargement des métriques…</p>
    </div>

    <div v-else-if="error" class="quality-view__error">
      <p>Erreur : {{ error }}</p>
    </div>

    <template v-else-if="overview">
      <!-- ── Retrieval ─────────────────────────────────────────────────── -->
      <section class="quality-family">
        <div class="quality-family__header">
          <h2>Retrieval</h2>
          <button type="button" class="quality-tooltip">
            <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
            <span class="quality-tooltip__text">Mesure si la recherche documentaire retrouve les bons passages en rejouant les paires Q/R de chaque collection contre son index actuel.</span>
          </button>
        </div>
        <p class="quality-family__description">
          Est-ce que la recherche documentaire retrouve les bons passages ? Mesuré en rejouant les paires
          question/réponse de chaque collection contre son index actuel.
        </p>

        <div v-if="retrievalMetrics.length === 0" class="quality-family__empty">
          Aucune évaluation de retrieval pour le moment.
        </div>
        <div v-else class="quality-family__table-wrap">
          <div class="quality-family__table-scroll">
          <table class="quality-table">
            <thead>
              <tr>
                <th>Collection</th>
                <th>Date</th>
                <th>Paires</th>
                <th>
                  Precision@k
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Parmi les passages retournés, quelle proportion est réellement pertinente.</span>
          </button>
                </th>
                <th>
                  Recall@k
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Parmi tous les passages pertinents, quelle proportion a été retrouvée.</span>
          </button>
                </th>
                <th>
                  MRR
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Mean Reciprocal Rank : plus le premier passage pertinent est tôt, plus le score est élevé.</span>
          </button>
                </th>
                <th>
                  nDCG
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Normalized Discounted Cumulative Gain : qualité du classement des passages, en pénalisant les pertinents mal positionnés.</span>
          </button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in retrievalMetrics" :key="run.runId">
                <td>{{ run.collectionName }}</td>
                <td>{{ formatDate(run.createdAt) }}</td>
                <td>{{ run.pairCount }}</td>
                <td>{{ pct(run.precisionAtK) }}</td>
                <td>{{ pct(run.recallAtK) }}</td>
                <td>{{ ratio(run.mrr) }}</td>
                <td>{{ ratio(run.ndcg) }}</td>
              </tr>
            </tbody>
          </table>
          </div>
        </div>
      </section>

      <!-- ── Feedback ──────────────────────────────────────────────────── -->
      <section class="quality-family">
        <div class="quality-family__header">
          <h2>Retours utilisateur</h2>
          <button type="button" class="quality-tooltip">
            <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
            <span class="quality-tooltip__text">Pouces haut/bas donnés par les utilisateurs sur les réponses de l'agent, avec les raisons sélectionnées pour les pouces bas.</span>
          </button>
        </div>
        <p class="quality-family__description">
          Ce que les utilisateurs pensent réellement des réponses reçues — pouce haut/bas et raisons données.
        </p>

        <div class="quality-family__grid">
          <article class="quality-metric">
            <p class="quality-metric__value">{{ pct(feedbackUpRatio) }}</p>
            <p class="quality-metric__label">Réponses appréciées</p>
            <p class="quality-metric__sample">n = {{ feedbackTotal }}</p>
            <p class="quality-metric__description">
              Proportion des retours qui sont un pouce haut plutôt qu'un pouce bas.
            </p>
          </article>

          <article v-if="topReason" class="quality-metric">
            <p class="quality-metric__value">{{ REASON_LABELS[topReason.reason] ?? topReason.reason }}</p>
            <p class="quality-metric__label">Principale raison de pouce bas</p>
            <p class="quality-metric__sample">{{ topReason.count }} / {{ topReason.total }}</p>
            <p class="quality-metric__description">La raison la plus souvent sélectionnée parmi les retours négatifs.</p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ feedback?.upCount ?? 0 }}</p>
            <p class="quality-metric__label">Pouces hauts</p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ feedback?.downCount ?? 0 }}</p>
            <p class="quality-metric__label">Pouces bas</p>
          </article>
        </div>
      </section>

      <!-- ── Discussion ───────────────────────────────────────────────── -->
      <section class="quality-family">
        <div class="quality-family__header">
          <h2>Score de discussion</h2>
          <button type="button" class="quality-tooltip">
            <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
            <span class="quality-tooltip__text">Évaluation LLM de la cohérence d'une conversation : pas de contradiction d'un tour à l'autre, bonne exploitation du contexte déjà échangé.</span>
          </button>
        </div>
        <p class="quality-family__description">
          Cohérence d'une conversation dans son ensemble : pas de contradiction d'un tour à l'autre,
          bonne exploitation du contexte déjà échangé. Le score LLM est déclenché à la demande.
        </p>

        <div class="quality-family__grid">
          <article class="quality-metric">
            <p class="quality-metric__value">{{ pct(discussionCoherenceRatio) }}</p>
            <p class="quality-metric__label">Cohérence</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">
              Proportion des conversations sans contradiction détectée par le LLM.
            </p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ ratio(discussion?.avgContextUsageScore ?? null) }}</p>
            <p class="quality-metric__label">Exploitation du contexte</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">
              Score moyen (0-1) d'utilisation du contexte conversationnel par le LLM.
            </p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ discussion?.avgRating?.toFixed(1) ?? '—' }}</p>
            <p class="quality-metric__label">Satisfaction moyenne (humain)</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">Note moyenne donnée par les utilisateurs (1-5).</p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ discussion?.avgMessageCount?.toFixed(1) ?? '—' }}</p>
            <p class="quality-metric__label">Messages / discussion</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">
              Nombre moyen de messages par conversation scorée.
            </p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ formatLatency(discussion?.avgLatencyMs ?? null) }}</p>
            <p class="quality-metric__label">Latence moyenne</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">
              Temps moyen d'appel LLM pour le scoring d'une discussion.
            </p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ formatCost(discussion?.estimatedCost ?? null) }}</p>
            <p class="quality-metric__label">Coût estimé</p>
            <p class="quality-metric__sample">n = {{ discussion?.totalConversations ?? 0 }}</p>
            <p class="quality-metric__description">
              0,75 × nombre total de tokens (tokens ≈ mots).
            </p>
          </article>
        </div>

        <!-- Conversations list with score + trigger -->
        <div v-if="conversations.length > 0 || selectedModelFilter !== 'all'" class="quality-family__table-wrap">
          <div class="quality-family__table-actions">
            <div class="quality-family__model-filter">
              <label for="quality-model-filter">Modèle</label>
              <select id="quality-model-filter" v-model="selectedModelFilter" class="fr-select">
                <option value="all">Tous les modèles</option>
                <option v-for="model in models" :key="model.id" :value="model.id">
                  {{ model.id }}
                </option>
              </select>
            </div>
            <div class="quality-family__scoring-model">
              <label for="quality-scoring-model">Scorer avec</label>
              <select id="quality-scoring-model" v-model="selectedScoringModel" class="fr-select">
                <option :value="null">Modèle par défaut</option>
                <option v-for="model in models" :key="model.id" :value="model.id">
                  {{ model.id }}
                </option>
              </select>
            </div>
            <button
              type="button"
              class="fr-btn fr-btn--sm fr-btn--tertiary"
              :disabled="isScoringAll || unscoredConversations.length === 0"
              @click="handleScoreAll"
            >
              <span v-if="isScoringAll">Scoring en cours…</span>
              <span v-else>Tout scorer ({{ unscoredConversations.length }})</span>
            </button>
          </div>
          <div class="quality-family__table-scroll">
          <table class="quality-table">
            <thead>
              <tr>
                <th>Discussion</th>
                <th>Messages</th>
                <th>
                  Cohérent (LLM)
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Le LLM juge si la conversation est cohérente d'un tour à l'autre (pas de contradiction).</span>
          </button>
                </th>
                <th>
                  Contexte (LLM)
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Score 0-1 : dans quelle mesure l'agent réutilise le contexte déjà échangé au lieu de se répéter ou d'ignorer les tours précédents.</span>
          </button>
                </th>
                <th>
                  Note (humain)
                  <button type="button" class="quality-tooltip">
                    <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
                    <span class="quality-tooltip__text">Note 1-5 donnée par l'utilisateur via le formulaire de feedback de discussion.</span>
          </button>
                </th>
                <th>Modèle</th>
                <th>Scores</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="conv in conversations" :key="conv.id">
                <tr>
                  <td>{{ conv.title || conv.id.slice(0, 8) }}</td>
                  <td>{{ conv.messageCount }}</td>
                  <td>
                    <span v-if="conv.coherent === null">—</span>
                    <span v-else-if="conv.coherent" class="quality-badge quality-badge--ok">✓</span>
                    <span v-else class="quality-badge quality-badge--ko">✗</span>
                  </td>
                  <td>{{ conv.contextUsageScore !== null ? ratio(conv.contextUsageScore) : '—' }}</td>
                  <td>{{ conv.humanRating ?? '—' }}</td>
                  <td><span class="quality-mono">{{ conv.llmModel ?? '—' }}</span></td>
                  <td>
                    <button
                      v-if="conv.scores.length > 0"
                      type="button"
                      class="fr-btn fr-btn--sm fr-btn--tertiary quality-family__expand-btn"
                      @click="toggleConversationExpand(conv.id)"
                    >
                      {{ conv.scores.length }}
                      <span class="quality-family__expand-icon" :class="{ 'quality-family__expand-icon--open': expandedConversations.has(conv.id) }">▼</span>
                    </button>
                    <span v-else>—</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      class="fr-btn fr-btn--sm fr-btn--tertiary"
                      :disabled="isScoring(conv.id) || isScoringAll"
                      @click="handleScoreConversation(conv.id)"
                    >
                      <span v-if="isScoring(conv.id)">En cours…</span>
                      <span v-else-if="conv.coherent === null">Scorer</span>
                      <span v-else>Re-scorer</span>
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedConversations.has(conv.id)" class="quality-family__score-detail">
                  <td colspan="8">
                    <table class="quality-table quality-table--inner">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Modèle</th>
                          <th>Messages</th>
                          <th>Cohérent</th>
                          <th>Contexte</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="score in conv.scores" :key="score.id">
                          <td>{{ formatDate(score.createdAt) }}</td>
                          <td><span class="quality-mono">{{ score.llmModel }}</span></td>
                          <td>{{ score.messageCount }}</td>
                          <td>
                            <span v-if="score.coherent" class="quality-badge quality-badge--ok">✓</span>
                            <span v-else class="quality-badge quality-badge--ko">✗</span>
                          </td>
                          <td>{{ ratio(score.contextUsageScore) }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          </div>

          <!-- Pagination -->
          <div v-if="totalPages > 1" class="quality-pagination">
            <button
              type="button"
              class="fr-btn fr-btn--sm fr-btn--tertiary"
              :disabled="currentPage <= 1"
              @click="goToPage(currentPage - 1)"
            >‹</button>
            <span class="quality-pagination__info">
              Page {{ currentPage }} / {{ totalPages }}
              ({{ conversationsTotal }} discussions)
            </span>
            <button
              type="button"
              class="fr-btn fr-btn--sm fr-btn--tertiary"
              :disabled="currentPage >= totalPages"
              @click="goToPage(currentPage + 1)"
            >›</button>
          </div>
        </div>
      </section>

      <!-- ── Groundedness ─────────────────────────────────────────────── -->
      <section class="quality-family">
        <div class="quality-family__header">
          <h2>Groundedness</h2>
          <button type="button" class="quality-tooltip">
            <span class="quality-tooltip__icon" aria-hidden="true">ℹ</span>
            <span class="quality-tooltip__text">Vérifie que chaque affirmation d'une réponse est réellement supportée par une source citée. Évalué par un LLM qui compare la réponse aux extraits fournis.</span>
          </button>
        </div>
        <p class="quality-family__description">
          Proportion des réponses dont chaque affirmation est réellement supportée par une source citée.
        </p>

        <div class="quality-family__grid">
          <article class="quality-metric">
            <p class="quality-metric__value">{{ pct(groundedRatio) }}</p>
            <p class="quality-metric__label">Réponses entièrement groundées</p>
            <p class="quality-metric__sample">n = {{ groundedness?.evaluatedCount ?? 0 }}</p>
            <p class="quality-metric__description">
              Proportion des réponses dont chaque affirmation est supportée par une source citée.
            </p>
          </article>

          <article class="quality-metric">
            <p class="quality-metric__value">{{ groundedness?.ungroundedCount ?? 0 }}</p>
            <p class="quality-metric__label">Réponses non groundées</p>
            <p class="quality-metric__sample">/ {{ groundedness?.evaluatedCount ?? 0 }}</p>
          </article>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.quality-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem 3rem;
  box-sizing: border-box;
}

.quality-view__header {
  max-width: 64rem;
  margin: 0 auto 2rem;
}

.quality-view__header h1 {
  margin: 0;
}

.quality-view__intro {
  margin: 0.5rem 0 1.25rem;
  color: var(--text-mention-grey);
  max-width: 42rem;
}

.quality-view__scope {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 1.25rem;
}

.quality-view__scope-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.quality-view__scope-field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.quality-view__scope-field select {
  max-width: 20rem;
}

.quality-view__loading,
.quality-view__error {
  max-width: 64rem;
  margin: 0 auto;
  padding: 2rem;
  text-align: center;
  color: var(--text-mention-grey);
}

.quality-view__error {
  color: var(--text-default-error);
}

.quality-family {
  max-width: 64rem;
  margin: 0 auto 2.5rem;
}

.quality-family__header {
  display: flex;
  align-items: baseline;
  gap: 0.625rem;
}

.quality-family__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.quality-family__description {
  margin: 0.375rem 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
  max-width: 42rem;
}

.quality-family__empty {
  padding: 1.5rem;
  text-align: center;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
  border: 1px dashed var(--border-default-grey);
  border-radius: 0.5rem;
}

.quality-family__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 1rem;
}

.quality-family__table-wrap {
  margin-top: 1rem;
}

.quality-family__table-scroll {
  overflow-x: auto;
}

.quality-family__expand-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.quality-family__expand-icon {
  font-size: 0.625rem;
  transition: transform 0.15s ease;
}

.quality-family__expand-icon--open {
  transform: rotate(180deg);
}

.quality-family__score-detail > td {
  padding: 0.5rem 0.75rem;
  background: var(--background-alt-grey);
}

.quality-table--inner {
  width: 100%;
  font-size: 0.8125rem;
}

.quality-table--inner th,
.quality-table--inner td {
  padding: 0.375rem 0.5rem;
}

.quality-metric {
  padding: 1.125rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.quality-metric__value {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
}

.quality-metric__label {
  margin: 0.25rem 0 0.125rem;
  font-weight: 700;
  font-size: 0.875rem;
}

.quality-metric__sample {
  margin: 0 0 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.quality-metric__description {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.quality-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.quality-table th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--border-default-grey);
  font-weight: 700;
  white-space: nowrap;
}

.quality-table td {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.quality-table tr:last-child td {
  border-bottom: none;
}

.quality-mono {
  font-family: monospace;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.quality-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 700;
}

.quality-badge--ok {
  background: var(--background-flat-success);
  color: white;
}

.quality-badge--ko {
  background: var(--background-flat-error);
  color: white;
}

.quality-badge--done {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

/* ── Tooltip ──────────────────────────────────────────────────────────── */

.quality-tooltip {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: help;
  background: none;
  border: none;
  padding: 0;
  font: inherit;
}

.quality-tooltip__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.125rem;
  height: 1.125rem;
  border-radius: 50%;
  background: var(--background-contrast-grey);
  color: var(--text-mention-grey);
  font-size: 0.7rem;
  font-weight: 700;
  font-style: italic;
}

.quality-tooltip__text {
  position: absolute;
  bottom: calc(100% + 0.5rem);
  left: 50%;
  transform: translateX(-50%);
  width: max-content;
  max-width: 18rem;
  padding: 0.5rem 0.75rem;
  background: var(--text-default-grey, #1e1e1e);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 400;
  line-height: 1.4;
  border-radius: 0.375rem;
  white-space: normal;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
  z-index: 10;
}

.quality-tooltip__text::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 0.375rem solid transparent;
  border-top-color: var(--text-default-grey, #1e1e1e);
}

.quality-tooltip:hover .quality-tooltip__text,
.quality-tooltip:focus .quality-tooltip__text {
  opacity: 1;
}

/* ── Table actions ────────────────────────────────────────────────────── */

.quality-family__table-actions {
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.quality-family__model-filter,
.quality-family__scoring-model {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.quality-family__model-filter label,
.quality-family__scoring-model label {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--text-mention-grey);
}

.quality-family__model-filter select,
.quality-family__scoring-model select {
  max-width: 16rem;
}

/* ── Pagination ───────────────────────────────────────────────────────── */

.quality-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1rem;
}

.quality-pagination__info {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
  white-space: nowrap;
}
</style>
