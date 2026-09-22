<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onMounted } from 'vue'
import { CHANGELOG_URL, useChangelog } from '../composables/useChangelog'

const emit = defineEmits<{
  close: []
}>()

const { latestSection, isLoading, error, fetchLatestChangelog } = useChangelog()
onMounted(fetchLatestChangelog)

const renderedNotes = computed(() =>
  latestSection.value ? DOMPurify.sanitize(marked.parse(latestSection.value, { async: false })) : '',
)
</script>

<template>
  <div class="release-notes-overlay" @click.self="emit('close')">
    <div class="release-notes" role="dialog" aria-modal="true" aria-labelledby="release-notes-title">
      <header class="release-notes__header">
        <h2 id="release-notes-title" class="release-notes__title">Notes de version</h2>
        <button type="button" class="release-notes__close" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>

      <div class="release-notes__body">
        <p v-if="isLoading" class="release-notes__hint">Chargement…</p>
        <p v-else-if="error" class="release-notes__error" role="alert">{{ error }}</p>
        <div v-else-if="renderedNotes" class="release-notes__content" v-html="renderedNotes" />
        <p v-else class="release-notes__hint">Aucune note de version disponible.</p>

        <a class="release-notes__link" :href="CHANGELOG_URL" target="_blank" rel="noopener">
          Voir tout l'historique sur GitHub
        </a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.release-notes-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.release-notes {
  width: 100%;
  max-width: 32rem;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.release-notes__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.release-notes__title {
  margin: 0;
  font-size: 1.0625rem;
}

.release-notes__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.release-notes__body {
  padding: 1rem 1.5rem 1.5rem;
  overflow-y: auto;
}

.release-notes__hint {
  color: var(--text-mention-grey);
}

.release-notes__error {
  color: var(--text-default-error);
}

.release-notes__content :deep(h2) {
  font-size: 1.125rem;
  margin: 0 0 0.75rem;
}

.release-notes__content :deep(h3) {
  font-size: 0.9375rem;
  margin: 1rem 0 0.375rem;
}

.release-notes__content :deep(ul) {
  margin: 0 0 0.5rem;
  padding-left: 1.25rem;
}

.release-notes__content :deep(li) {
  font-size: 0.875rem;
  margin-bottom: 0.25rem;
}

.release-notes__content :deep(a) {
  color: var(--text-action-high-blue-france);
}

.release-notes__link {
  display: inline-block;
  margin-top: 1rem;
  color: var(--text-action-high-blue-france);
  font-size: 0.8125rem;
}
</style>
