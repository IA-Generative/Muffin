<script setup lang="ts">
import { computed, nextTick, ref, toRef, watch } from 'vue'
import { useTaskLogs } from '../composables/useTaskLogs'

const props = defineProps<{
  // API path of the lines: a task's (/api/tasks/<id>/logs) or a document's.
  path: string
  // Whether what logs them still runs: new lines are then fetched as they come.
  live: boolean
  // A document's lines come from several tasks: each says which.
  showTaskName?: boolean
}>()

const LEVELS = [
  { value: '', label: 'Tous les niveaux' },
  { value: 'INFO', label: 'Info et plus' },
  { value: 'WARNING', label: 'Avertissements et erreurs' },
  { value: 'ERROR', label: 'Erreurs' },
]

const level = ref('')
const { entries, isLoading, error } = useTaskLogs(toRef(props, 'path'), toRef(props, 'live'), level)

const timeFormatter = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
function formatTime(iso: string) {
  return timeFormatter.format(new Date(iso))
}

function shortTaskName(taskName: string) {
  return taskName.split('.').pop() ?? taskName
}

const levelClass = (entryLevel: string) => `log-viewer__level--${entryLevel.toLowerCase()}`

// Follows the new lines as long as the reader is at the bottom; scrolled up, they stay where they are.
const container = ref<HTMLElement>()
const atBottom = ref(true)
function onScroll() {
  const element = container.value
  if (element) atBottom.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}
watch(
  () => entries.value.length,
  async () => {
    if (!atBottom.value) return
    await nextTick()
    if (container.value) container.value.scrollTop = container.value.scrollHeight
  },
)

const isEmpty = computed(() => !isLoading.value && entries.value.length === 0)
</script>

<template>
  <div class="log-viewer">
    <div class="log-viewer__toolbar">
      <select v-model="level" class="fr-select log-viewer__level-select" aria-label="Niveau des logs">
        <option v-for="option in LEVELS" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <span v-if="live" class="log-viewer__live">● En direct</span>
    </div>
    <p v-if="error" class="log-viewer__error" role="alert">{{ error }}</p>
    <div ref="container" class="log-viewer__content" @scroll="onScroll">
      <p v-if="isLoading" class="log-viewer__empty">Chargement…</p>
      <p v-else-if="isEmpty" class="log-viewer__empty">
        {{ live ? 'Aucun log pour le moment.' : 'Aucun log.' }}
      </p>
      <div v-for="entry in entries" :key="entry.id" class="log-viewer__line">
        <span class="log-viewer__time">{{ formatTime(entry.ts) }}</span>
        <span class="log-viewer__level" :class="levelClass(entry.level)">{{ entry.level }}</span>
        <span v-if="showTaskName" class="log-viewer__task">{{ shortTaskName(entry.taskName) }}</span>
        <span class="log-viewer__message">{{ entry.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-height: 0;
  flex: 1;
}

.log-viewer__toolbar {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.log-viewer__level-select {
  width: auto;
  margin: 0;
}

.log-viewer__live {
  font-size: 0.8125rem;
  color: var(--text-default-success, #18753c);
}

.log-viewer__error {
  margin: 0;
  color: var(--text-default-error, #ce0500);
}

.log-viewer__content {
  flex: 1;
  min-height: 12rem;
  overflow-y: auto;
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-grey, #f6f6f6);
  color: var(--text-default-grey, #333);
  font-size: 0.8125rem;
  font-family: ui-monospace, monospace;
}

.log-viewer__empty {
  margin: 0;
  color: var(--text-mention-grey, #888);
}

.log-viewer__line {
  display: flex;
  gap: 0.75rem;
  align-items: baseline;
  padding: 0.0625rem 0;
}

.log-viewer__time,
.log-viewer__task {
  flex-shrink: 0;
  color: var(--text-mention-grey, #888);
}

.log-viewer__level {
  flex-shrink: 0;
  width: 4.5rem;
  font-weight: 600;
}

.log-viewer__level--warning {
  color: var(--text-default-warning, #b34000);
}

.log-viewer__level--error,
.log-viewer__level--critical {
  color: var(--text-default-error, #ce0500);
}

.log-viewer__level--success {
  color: var(--text-default-success, #18753c);
}

.log-viewer__message {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
