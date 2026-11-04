<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useAdminModels } from '../composables/useAdminModels'
import type { ModelCapability, ModelProfile } from '../types/model'

const { models, classifierModel, isLoading, error, fetchModels, saveModel, saveClassifierModel } = useAdminModels()

// Les capacités sont calculées par le backend : on les montre, on ne les édite pas.
const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  chat: 'Conversation',
  vision: 'Image en entrée',
  embeddings: 'Embeddings',
  image_generation: "Génération d'images",
  speech_to_text: 'Transcription',
  text_to_speech: 'Synthèse vocale',
}

interface Draft {
  score: number
  description: string
  autoEnabled: boolean
}

const drafts = reactive<Record<string, Draft>>({})
const savedId = ref<string | null>(null)
const savingId = ref<string | null>(null)

function syncDrafts() {
  for (const model of models.value) {
    drafts[model.id] = { score: model.score, description: model.description ?? '', autoEnabled: model.auto_enabled }
  }
}

onMounted(async () => {
  await fetchModels()
  syncDrafts()
})

const chatModels = computed(() => models.value.filter((model) => model.capabilities.includes('chat')))
const otherModels = computed(() => models.value.filter((model) => !model.capabilities.includes('chat')))

function isDirty(model: ModelProfile): boolean {
  const draft = drafts[model.id]
  return (
    !!draft &&
    (draft.score !== model.score ||
      draft.description.trim() !== (model.description ?? '') ||
      draft.autoEnabled !== model.auto_enabled)
  )
}

function levelLabel(score: number): string {
  if (score < 25) return 'Tâches simples'
  if (score < 50) return 'Tâches courantes'
  if (score < 75) return 'Tâches élaborées'
  return 'Tâches très complexes'
}

async function save(model: ModelProfile) {
  const draft = drafts[model.id]
  savingId.value = model.id
  const ok = await saveModel(model.id, {
    score: draft.score,
    description: draft.description.trim() || null,
    auto_enabled: draft.autoEnabled,
  })
  savingId.value = null
  if (!ok) return
  savedId.value = model.id
  setTimeout(() => {
    if (savedId.value === model.id) savedId.value = null
  }, 2000)
}

async function changeClassifier(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  await saveClassifierModel(value || null)
}
</script>

<template>
  <section class="admin-view">
    <router-link to="/admin" class="admin-view__back">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
      </svg>
      Administration
    </router-link>
    <div class="admin-view__header">
      <h1>Modèles et mode Auto</h1>
    </div>
    <p class="admin-view__intro">
      En mode Auto, chaque demande est classée par niveau, complexité et intention, puis confiée au modèle le moins
      puissant qui sait la traiter. Donnez à chaque modèle un score de 0 (tâche triviale) à 100 (tâche très complexe) et
      dites ce qu'il fait correctement. Les capacités techniques sont détectées automatiquement.
    </p>

    <p v-if="error" class="admin-view__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="admin-view__empty">Chargement…</p>

    <template v-else>
      <div class="admin-card">
        <h2 class="admin-card__title">Modèle de classification</h2>
        <p class="admin-card__intro">
          Il note chaque demande avant le choix du modèle, donc il est appelé à chaque message : un modèle léger suffit.
        </p>
        <div class="admin-card__field">
          <label for="classifier-model">Modèle</label>
          <select id="classifier-model" class="fr-select" :value="classifierModel ?? ''" @change="changeClassifier">
            <option value="">Le moins puissant des modèles utilisables en Auto (par défaut)</option>
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
        </div>
      </div>

      <p v-if="chatModels.length === 0 && !error" class="admin-view__empty">Aucun modèle de conversation disponible.</p>

      <article v-for="model in chatModels" :key="model.id" class="admin-card model-card">
        <header class="model-card__header">
          <h2 class="model-card__name">{{ model.id }}</h2>
          <ul class="model-card__tags" aria-label="Capacités">
            <li v-for="capability in model.capabilities" :key="capability" class="fr-badge fr-badge--sm fr-badge--info fr-badge--no-icon">
              {{ CAPABILITY_LABELS[capability] }}
            </li>
          </ul>
        </header>

        <div class="admin-card__field">
          <label :for="`score-${model.id}`">
            Niveau de tâche maîtrisé : <strong>{{ drafts[model.id]?.score }}</strong> / 100
            <span class="model-card__level">({{ levelLabel(drafts[model.id]?.score ?? 0) }})</span>
          </label>
          <input
            v-if="drafts[model.id]"
            :id="`score-${model.id}`"
            v-model.number="drafts[model.id].score"
            type="range"
            min="0"
            max="100"
            step="1"
            class="model-card__range"
          />
        </div>

        <div v-if="drafts[model.id]" class="admin-card__field">
          <label :for="`description-${model.id}`">Ce qu'il fait correctement</label>
          <textarea
            :id="`description-${model.id}`"
            v-model="drafts[model.id].description"
            class="fr-input"
            rows="2"
            maxlength="1000"
            placeholder="Ex. : questions-réponses sur documents, résumés courts, reformulation. Pas fiable en calcul."
          />
        </div>

        <div v-if="drafts[model.id]" class="fr-checkbox-group fr-checkbox-group--sm">
          <input :id="`auto-${model.id}`" v-model="drafts[model.id].autoEnabled" type="checkbox" />
          <label class="fr-label" :for="`auto-${model.id}`">Utilisable en mode Auto</label>
        </div>

        <div class="admin-card__footer">
          <span v-if="savedId === model.id" class="admin-card__saved">Enregistré</span>
          <span v-else-if="!model.described" class="admin-card__hint">Pas encore évalué : score par défaut.</span>
          <button type="button" class="fr-btn fr-btn--sm" :disabled="!isDirty(model) || savingId === model.id" @click="save(model)">
            Enregistrer
          </button>
        </div>
      </article>

      <div v-if="otherModels.length > 0" class="admin-card">
        <h2 class="admin-card__title">Autres modèles du hub</h2>
        <p class="admin-card__intro">Pas de conversation : ils ne sont jamais choisis en mode Auto.</p>
        <ul class="other-models">
          <li v-for="model in otherModels" :key="model.id" class="other-models__item">
            <span>{{ model.id }}</span>
            <ul class="model-card__tags" aria-label="Capacités">
              <li v-for="capability in model.capabilities" :key="capability" class="fr-badge fr-badge--sm fr-badge--no-icon">
                {{ CAPABILITY_LABELS[capability] }}
              </li>
              <li v-if="model.capabilities.length === 0" class="fr-badge fr-badge--sm fr-badge--no-icon">Non détecté</li>
            </ul>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.admin-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.admin-view__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  max-width: 48rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__back:hover {
  color: var(--text-default-grey);
}

.admin-view__header {
  max-width: 48rem;
  margin: 0 auto;
}

.admin-view__header h1 {
  margin: 0;
}

.admin-view__intro {
  max-width: 48rem;
  margin: 0.5rem auto 1.5rem;
  color: var(--text-mention-grey);
}

.admin-view__empty,
.admin-view__error {
  max-width: 48rem;
  margin: 2rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.admin-view__error {
  color: var(--text-default-error);
}

.admin-card {
  max-width: 48rem;
  margin: 0 auto 1rem;
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.admin-card__title {
  margin: 0 0 0.5rem;
  font-size: 1.0625rem;
}

.admin-card__intro {
  margin: 0 0 1.25rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.admin-card__field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-bottom: 1rem;
}

.admin-card__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.admin-card__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.admin-card__footer {
  margin-top: 1rem;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.admin-card__saved {
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.model-card__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.model-card__name {
  margin: 0;
  font-size: 1.0625rem;
  word-break: break-all;
}

.model-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.model-card__level {
  font-weight: 400;
  color: var(--text-mention-grey);
}

.model-card__range {
  width: 100%;
}

.other-models {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.other-models__item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.875rem;
}
</style>
