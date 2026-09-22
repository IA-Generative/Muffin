<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { usePrompts } from '../composables/usePrompts'
import PromptEditor from './PromptEditor.vue'

const { summaries: prompts, isLoading, error, fetchPrompts } = usePrompts()
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
      <h1>Prompts de l'agent</h1>
    </div>
    <p class="admin-view__intro">
      Publier une nouvelle version prend effet pour les prochains runs sans redéploiement (les workers rafraîchissent
      leur cache dans la minute). L'historique permet de revenir à une version précédente à tout moment.
    </p>

    <p v-if="error" class="admin-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading" class="admin-view__empty">Chargement…</p>
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
  margin: 3rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.admin-view__error {
  color: var(--text-default-error);
}

.prompt-carousel {
  max-width: 48rem;
  margin: 0 auto;
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

.prompt-carousel__card {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}
</style>
