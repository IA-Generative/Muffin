<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useAdminSettings } from '../composables/useAdminSettings'
import { useEmbeddingModels } from '../composables/useEmbeddingModels'
import { usePrompts } from '../composables/usePrompts'
import CguEditor from './CguEditor.vue'
import PromptEditor from './PromptEditor.vue'

const { embeddingModel, isLoading, error, fetchAdminSettings, updateEmbeddingModel } = useAdminSettings()
const { models, isLoading: isLoadingModels, error: modelsError } = useEmbeddingModels()
const { summaries: prompts, isLoading: isLoadingPrompts, error: promptsError, fetchPrompts } = usePrompts()
onMounted(fetchAdminSettings)
onMounted(fetchPrompts)

const promptIndex = ref(0)
watch(prompts, (value) => {
  if (promptIndex.value >= value.length) promptIndex.value = 0
})
function prevPrompt() {
  promptIndex.value = promptIndex.value === 0 ? prompts.value.length - 1 : promptIndex.value - 1
}
function nextPrompt() {
  promptIndex.value = promptIndex.value === prompts.value.length - 1 ? 0 : promptIndex.value + 1
}

const draft = ref('')
watch(
  embeddingModel,
  (value) => {
    if (value) draft.value = value
  },
  { immediate: true },
)

const saved = ref(false)
async function save() {
  if (!draft.value) return
  await updateEmbeddingModel(draft.value)
  saved.value = true
  setTimeout(() => (saved.value = false), 2000)
}
</script>

<template>
  <section class="admin-view">
    <div class="admin-view__header">
      <h1>Administration</h1>
    </div>
    <p class="admin-view__intro">Réglages globaux, valables pour toutes les collections.</p>

    <p v-if="error" class="admin-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading" class="admin-view__empty">Chargement…</p>

    <form v-else class="admin-card" @submit.prevent="save">
      <h2 class="admin-card__title">Modèle d'embedding</h2>
      <p class="admin-card__intro">
        Utilisé pour comparer une question à la description de chaque collection et déterminer laquelle cibler.
        Ce modèle est le même pour toutes les collections : il ne peut pas être choisi par collection, sinon les
        embeddings ne seraient plus comparables entre eux.
      </p>

      <div class="admin-card__field">
        <label for="admin-embedding-model">Modèle</label>
        <select id="admin-embedding-model" v-model="draft" class="fr-select" :disabled="isLoadingModels">
          <option v-for="model in models" :key="model.id" :value="model.id">{{ model.id }}</option>
        </select>
        <p v-if="modelsError" class="admin-card__hint">{{ modelsError }}</p>
        <p v-else-if="!isLoadingModels && models.length === 0" class="admin-card__hint">Aucun modèle disponible.</p>
        <p v-else-if="!embeddingModel" class="admin-card__hint">
          Aucun modèle choisi pour l'instant : le premier modèle d'embedding disponible sur le hub est utilisé par
          défaut.
        </p>
      </div>

      <div class="admin-card__footer">
        <span v-if="saved" class="admin-card__saved">Enregistré</span>
        <button type="submit" class="fr-btn" :disabled="!draft">Enregistrer</button>
      </div>
    </form>

    <section class="admin-view__section">
      <h2 class="admin-view__section-title">Prompts de l'agent</h2>
      <p class="admin-view__intro admin-view__intro--section">
        Publier une nouvelle version prend effet pour les prochains runs sans redéploiement (les workers rafraîchissent
        leur cache dans la minute). L'historique permet de revenir à une version précédente à tout moment.
      </p>
      <p v-if="promptsError" class="admin-view__error" role="alert">{{ promptsError }}</p>
      <p v-else-if="isLoadingPrompts" class="admin-view__empty">Chargement…</p>
      <p v-else-if="prompts.length === 0" class="admin-view__empty">Aucun prompt.</p>
      <div v-else class="prompt-carousel">
        <div class="prompt-carousel__nav">
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm prompt-carousel__arrow"
            aria-label="Prompt précédent"
            :disabled="prompts.length < 2"
            @click="prevPrompt"
          >
            ‹
          </button>
          <div class="prompt-carousel__dots">
            <button
              v-for="(prompt, index) in prompts"
              :key="prompt.name"
              type="button"
              class="prompt-carousel__dot"
              :class="{ 'prompt-carousel__dot--active': index === promptIndex }"
              :aria-label="`Aller au prompt ${prompt.name}`"
              :aria-current="index === promptIndex"
              @click="promptIndex = index"
            />
          </div>
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm prompt-carousel__arrow"
            aria-label="Prompt suivant"
            :disabled="prompts.length < 2"
            @click="nextPrompt"
          >
            ›
          </button>
        </div>
        <p class="prompt-carousel__position">{{ promptIndex + 1 }} / {{ prompts.length }}</p>
        <PromptEditor
          :key="prompts[promptIndex].name"
          class="prompt-carousel__card"
          :name="prompts[promptIndex].name"
          :active-version="prompts[promptIndex].active_version"
        />
      </div>
    </section>

    <section class="admin-view__section">
      <h2 class="admin-view__section-title">Conditions générales d'utilisation</h2>
      <p class="admin-view__intro admin-view__intro--section">
        Publier une nouvelle version force chaque utilisateur ayant déjà accepté une version précédente à
        accepter celle-ci avant de pouvoir continuer à utiliser l'app - voir #127.
      </p>
      <CguEditor class="admin-card-frame" />
    </section>
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
  margin: 3rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.admin-view__error {
  color: var(--text-default-error);
}

.admin-card {
  max-width: 48rem;
  margin: 0 auto;
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
  margin-top: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.admin-card__saved {
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.admin-view__section {
  max-width: 48rem;
  margin: 2rem auto 0;
}

.admin-view__section-title {
  font-size: 1.0625rem;
  margin: 0 0 0.5rem;
}

.admin-view__intro--section {
  margin: 0 0 1rem;
}

.prompt-carousel__nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
}

.prompt-carousel__arrow {
  font-size: 1.25rem;
  line-height: 1;
  padding: 0.25rem 0.75rem;
}

.prompt-carousel__dots {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.prompt-carousel__dot {
  width: 0.5rem;
  height: 0.5rem;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--border-default-grey);
  cursor: pointer;
}

.prompt-carousel__dot--active {
  background: var(--background-action-high-blue-france);
}

.prompt-carousel__position {
  margin: 0.375rem 0 0.75rem;
  text-align: center;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.prompt-carousel__card,
.admin-card-frame {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}
</style>
