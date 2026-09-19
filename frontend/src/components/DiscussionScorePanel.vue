<script setup lang="ts">
import { ref } from 'vue'
import { useChat } from '../composables/useChat'

defineEmits<{ close: [] }>()

const {
  activeDiscussionScores,
  triggerDiscussionScore,
  activeId,
  activeDiscussionFeedback,
  submitDiscussionFeedback,
  refreshDiscussionFeedback,
} = useChat()

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}

function scoreColor(score: number): string {
  if (score >= 0.8) return 'var(--text-default-success)'
  if (score >= 0.5) return 'var(--text-default-warning)'
  return 'var(--text-default-error)'
}

// --- Human feedback form state ---
const feedbackRating = ref<number>(0)
const feedbackCoherent = ref<boolean>(true)
const feedbackContextScore = ref<number | null>(null)
const feedbackComment = ref<string>('')
const feedbackSubmitting = ref<boolean>(false)

function setRating(n: number) {
  feedbackRating.value = n
}

async function handleSubmitFeedback() {
  if (feedbackRating.value === 0) return
  feedbackSubmitting.value = true
  await submitDiscussionFeedback(activeId.value, {
    rating: feedbackRating.value,
    coherent: feedbackCoherent.value,
    contextUsageScore: feedbackContextScore.value,
    comment: feedbackComment.value || null,
  })
  feedbackSubmitting.value = false
  // Reset form after submit
  feedbackRating.value = 0
  feedbackCoherent.value = true
  feedbackContextScore.value = null
  feedbackComment.value = ''
}

// Load existing feedback when panel opens
refreshDiscussionFeedback(activeId.value)
</script>

<template>
  <aside class="discussion-panel">
    <header class="discussion-panel__header">
      <h2 class="discussion-panel__title">Évaluation de la discussion</h2>
      <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="$emit('close')">
        Fermer
      </button>
    </header>

    <div class="discussion-panel__body">
      <button
        type="button"
        class="fr-btn discussion-panel__trigger"
        :disabled="activeId === 'default'"
        @click="triggerDiscussionScore(activeId)"
      >
        Évaluer la discussion
      </button>
      <p v-if="activeId === 'default'" class="discussion-panel__hint">
        Démarrez une conversation avant de l'évaluer.
      </p>

      <ul v-if="activeDiscussionScores.length" class="discussion-panel__scores">
        <li
          v-for="score in activeDiscussionScores"
          :key="score.id"
          class="discussion-panel__score"
        >
          <div class="discussion-panel__score-header">
            <span class="discussion-panel__score-date">{{ formatDate(score.createdAt) }}</span>
            <span
              class="discussion-panel__badge"
              :class="score.coherent ? 'discussion-panel__badge--ok' : 'discussion-panel__badge--ko'"
            >
              {{ score.coherent ? 'Cohérente' : 'Incohérente' }}
            </span>
          </div>
          <dl class="discussion-panel__metrics">
            <div class="discussion-panel__metric">
              <dt>Messages</dt>
              <dd>{{ score.messageCount }}</dd>
            </div>
            <div class="discussion-panel__metric">
              <dt>Utilisation du contexte</dt>
              <dd :style="{ color: scoreColor(score.contextUsageScore) }">
                {{ Math.round(score.contextUsageScore * 100) }}%
              </dd>
            </div>
            <div class="discussion-panel__metric">
              <dt>Modèle</dt>
              <dd>{{ score.llmModel }}</dd>
            </div>
          </dl>
          <div v-if="score.coherenceIssues.length" class="discussion-panel__issues">
            <p class="discussion-panel__issues-label">Problèmes de cohérence :</p>
            <ul>
              <li v-for="(issue, index) in score.coherenceIssues" :key="`coherence-${index}`">{{ issue }}</li>
            </ul>
          </div>
          <div v-if="score.contextUsageIssues.length" class="discussion-panel__issues">
            <p class="discussion-panel__issues-label">Problèmes d'utilisation du contexte :</p>
            <ul>
              <li v-for="(issue, index) in score.contextUsageIssues" :key="`context-${index}`">{{ issue }}</li>
            </ul>
          </div>
          <details v-if="score.reasoning" class="discussion-panel__reasoning">
            <summary>Raisonnement</summary>
            <p>{{ score.reasoning }}</p>
          </details>
        </li>
      </ul>
      <p v-else class="discussion-panel__empty">Aucune évaluation pour cette conversation.</p>

      <hr class="discussion-panel__divider" />

      <section class="discussion-panel__human">
        <h3 class="discussion-panel__human-title">Votre évaluation</h3>
        <p class="discussion-panel__human-hint">
          Notez cette conversation dans son ensemble (le complément humain de l'évaluation LLM).
        </p>
        <form class="discussion-panel__form" @submit.prevent="handleSubmitFeedback">
          <div class="discussion-panel__field">
            <label class="discussion-panel__label" for="feedback-rating">Satisfaction globale</label>
            <div id="feedback-rating" class="discussion-panel__stars" aria-label="Note de 1 à 5 étoiles">
              <button
                v-for="n in 5"
                :key="n"
                type="button"
                class="discussion-panel__star"
                :class="{ 'discussion-panel__star--active': n <= feedbackRating }"
                :aria-label="`${n} sur 5`"
                @click="setRating(n)"
              >
                ★
              </button>
            </div>
          </div>

          <div class="discussion-panel__field">
            <span id="feedback-coherent-label" class="discussion-panel__label">La discussion est-elle cohérente ?</span>
            <div role="radiogroup" aria-labelledby="feedback-coherent-label">
              <label class="discussion-panel__radio">
                <input v-model="feedbackCoherent" type="radio" :value="true" />
                Oui
              </label>
              <label class="discussion-panel__radio">
                <input v-model="feedbackCoherent" type="radio" :value="false" />
                Non
              </label>
            </div>
          </div>

          <div class="discussion-panel__field">
            <label class="discussion-panel__label" for="feedback-context-slider">
              Utilisation du contexte (optionnel)
              <span class="discussion-panel__slider-value">
                {{ feedbackContextScore !== null ? Math.round(feedbackContextScore * 100) + '%' : '—' }}
              </span>
            </label>
            <input
              id="feedback-context-slider"
              v-model.number="feedbackContextScore"
              type="range"
              min="0"
              max="1"
              step="0.1"
              class="discussion-panel__slider"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="feedbackContextScore !== null ? Math.round(feedbackContextScore * 100) : undefined"
            />
          </div>

          <div class="discussion-panel__field">
            <label class="discussion-panel__label" for="feedback-comment">Commentaire (optionnel)</label>
            <textarea
              id="feedback-comment"
              v-model="feedbackComment"
              class="discussion-panel__textarea fr-input"
              rows="3"
              placeholder="Vos remarques sur cette conversation…"
            />
          </div>

          <button
            type="submit"
            class="fr-btn discussion-panel__submit"
            :disabled="feedbackRating === 0 || feedbackSubmitting"
          >
            {{ feedbackSubmitting ? 'Envoi…' : 'Envoyer mon évaluation' }}
          </button>
        </form>

        <ul v-if="activeDiscussionFeedback.length" class="discussion-panel__feedback-list">
          <li
            v-for="fb in activeDiscussionFeedback"
            :key="fb.id"
            class="discussion-panel__feedback-item"
          >
            <div class="discussion-panel__feedback-header">
              <span class="discussion-panel__stars-display">
                {{ '★'.repeat(fb.rating) }}<span class="discussion-panel__stars-empty">{{ '★'.repeat(5 - fb.rating) }}</span>
              </span>
              <span class="discussion-panel__feedback-date">{{ formatDate(fb.createdAt) }}</span>
            </div>
            <span
              class="discussion-panel__badge"
              :class="fb.coherent ? 'discussion-panel__badge--ok' : 'discussion-panel__badge--ko'"
            >
              {{ fb.coherent ? 'Cohérente' : 'Incohérente' }}
            </span>
            <p v-if="fb.comment" class="discussion-panel__feedback-comment">{{ fb.comment }}</p>
          </li>
        </ul>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.discussion-panel {
  display: flex;
  flex-direction: column;
  width: 24rem;
  max-width: 90vw;
  border-left: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  height: 100%;
  overflow: hidden;
}

.discussion-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.discussion-panel__title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
}

.discussion-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.discussion-panel__trigger {
  align-self: flex-start;
}

.discussion-panel__hint {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  margin: 0;
}

.discussion-panel__scores {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.discussion-panel__score {
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
}

.discussion-panel__score-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.discussion-panel__score-date {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.discussion-panel__badge {
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
}

.discussion-panel__badge--ok {
  background: var(--background-success-default);
  color: var(--text-inverted-default);
}

.discussion-panel__badge--ko {
  background: var(--background-error-default);
  color: var(--text-inverted-default);
}

.discussion-panel__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 0 0 0.5rem;
}

.discussion-panel__metric {
  display: flex;
  flex-direction: column;
}

.discussion-panel__metric dt {
  font-size: 0.6875rem;
  color: var(--text-mention-grey);
}

.discussion-panel__metric dd {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 600;
}

.discussion-panel__issues {
  margin-bottom: 0.5rem;
}

.discussion-panel__issues-label {
  font-size: 0.75rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
}

.discussion-panel__issues ul {
  margin: 0;
  padding-left: 1rem;
  font-size: 0.75rem;
}

.discussion-panel__reasoning summary {
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--text-mention-grey);
}

.discussion-panel__reasoning p {
  font-size: 0.75rem;
  margin: 0.5rem 0 0;
  line-height: 1.4;
}

.discussion-panel__empty {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
  text-align: center;
  margin: 1rem 0;
}

.discussion-panel__divider {
  border: none;
  border-top: 1px solid var(--border-default-grey);
  margin: 0.5rem 0;
}

.discussion-panel__human {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.discussion-panel__human-title {
  font-size: 0.875rem;
  font-weight: 600;
  margin: 0;
}

.discussion-panel__human-hint {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  margin: 0;
}

.discussion-panel__form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.discussion-panel__field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.discussion-panel__label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-mention-grey);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.discussion-panel__slider-value {
  font-weight: 400;
  font-size: 0.6875rem;
}

.discussion-panel__stars {
  display: flex;
  gap: 0.125rem;
}

.discussion-panel__star {
  background: none;
  border: none;
  font-size: 1.25rem;
  color: var(--border-default-grey);
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.discussion-panel__star--active {
  color: var(--text-default-warning);
}

.discussion-panel__radio {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.8125rem;
}

.discussion-panel__slider {
  width: 100%;
}

.discussion-panel__textarea {
  font-size: 0.8125rem;
}

.discussion-panel__submit {
  align-self: flex-start;
}

.discussion-panel__feedback-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.discussion-panel__feedback-item {
  padding: 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.discussion-panel__feedback-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.discussion-panel__stars-display {
  font-size: 0.875rem;
  color: var(--text-default-warning);
}

.discussion-panel__stars-empty {
  color: var(--border-default-grey);
}

.discussion-panel__feedback-date {
  font-size: 0.6875rem;
  color: var(--text-mention-grey);
}

.discussion-panel__feedback-comment {
  font-size: 0.75rem;
  margin: 0;
  line-height: 1.4;
}
</style>
