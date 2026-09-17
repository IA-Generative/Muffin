<script setup lang="ts">
import type { Source } from '../types/chat'

defineProps<{
  sources: Source[]
}>()

defineEmits<{
  close: []
}>()
</script>

<template>
  <aside class="sources-panel">
    <div class="sources-panel__header">
      <h2>Sources</h2>
      <button type="button" class="sources-panel__close" aria-label="Fermer" @click="$emit('close')">
        ✕
      </button>
    </div>

    <ul class="sources-panel__list">
      <li v-for="source in sources" :key="source.url ?? source.title" class="sources-panel__item">
        <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">
          <span class="sources-panel__title">{{ source.title }}</span>
          <span class="sources-panel__url">{{ source.url }}</span>
        </a>
        <div v-else class="sources-panel__item-static">
          <span class="sources-panel__title">{{ source.title }}</span>
        </div>
      </li>
    </ul>
  </aside>
</template>

<style scoped>
.sources-panel {
  width: 320px;
  flex-shrink: 0;
  height: 100%;
  padding: 1.25rem;
  background: var(--background-alt-grey);
  border-left: 1px solid var(--border-default-grey);
  box-sizing: border-box;
  overflow-y: auto;
}

.sources-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sources-panel__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.sources-panel__close {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-mention-grey);
}

.sources-panel__list {
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.sources-panel__item a {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  text-decoration: none;
}

.sources-panel__item a:hover {
  border-color: var(--border-action-high-blue-france);
}

.sources-panel__item-static {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
}

.sources-panel__title {
  color: var(--text-action-high-blue-france);
  font-weight: 700;
}

.sources-panel__url {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
