<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'
import { useCgu } from '../composables/useCgu'

// Read-only, dismissible - unlike CguGateModal (mandatory, no close button). Reuses the same
// useCgu() singleton state (already fetched by App.vue at login) rather than fetching again -
// this is always the *active* version, the same one a gate (if shown) would ask to accept.
const emit = defineEmits<{
  close: []
}>()

const { status } = useCgu()

const renderedContent = computed(() =>
  status.value?.content ? DOMPurify.sanitize(marked.parse(status.value.content, { async: false })) : '',
)
</script>

<template>
  <div class="cgu-viewer-overlay" @click.self="emit('close')">
    <div class="cgu-viewer" role="dialog" aria-modal="true" aria-labelledby="cgu-viewer-title">
      <header class="cgu-viewer__header">
        <h2 id="cgu-viewer-title" class="cgu-viewer__title">Conditions générales d'utilisation</h2>
        <button type="button" class="cgu-viewer__close" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>
      <div class="cgu-viewer__body">
        <div v-if="renderedContent" class="cgu-viewer__content" v-html="renderedContent" />
        <p v-else class="cgu-viewer__hint">Aucune CGU disponible.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cgu-viewer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.cgu-viewer {
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

.cgu-viewer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.cgu-viewer__title {
  margin: 0;
  font-size: 1.0625rem;
}

.cgu-viewer__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.cgu-viewer__body {
  padding: 1rem 1.5rem 1.5rem;
  overflow-y: auto;
}

.cgu-viewer__hint {
  color: var(--text-mention-grey);
}

.cgu-viewer__content :deep(h1) {
  font-size: 1.125rem;
  margin: 0 0 0.75rem;
}

.cgu-viewer__content :deep(h2) {
  font-size: 1rem;
  margin: 1.25rem 0 0.5rem;
}

.cgu-viewer__content :deep(p),
.cgu-viewer__content :deep(li) {
  font-size: 0.875rem;
  line-height: 1.5;
}
</style>
