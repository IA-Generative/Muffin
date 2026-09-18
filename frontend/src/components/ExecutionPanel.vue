<script setup lang="ts">
import type { ExecutionEvent } from '../types/chat'

const props = defineProps<{
  events: ExecutionEvent[] | undefined
  error?: boolean
}>()

defineEmits<{
  close: []
}>()

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

// Groups consecutive events sharing a task_id under that task, so a fan-out of several parallel
// research tasks reads as distinct sub-sections instead of one flat interleaved list.
const groups = (() => {
  const result: { taskId?: string; events: ExecutionEvent[] }[] = []
  for (const event of props.events ?? []) {
    const last = result[result.length - 1]
    if (last && last.taskId === event.taskId) last.events.push(event)
    else result.push({ taskId: event.taskId, events: [event] })
  }
  return result
})()
</script>

<template>
  <aside class="execution-panel">
    <div class="execution-panel__header">
      <h2>Détail de l'exécution</h2>
      <button type="button" class="execution-panel__close" aria-label="Fermer" @click="$emit('close')">✕</button>
    </div>

    <p v-if="error" class="execution-panel__error">Impossible de charger le détail de l'exécution.</p>
    <p v-else-if="events === undefined" class="execution-panel__empty">Chargement…</p>
    <p v-else-if="events.length === 0" class="execution-panel__empty">Aucun détail disponible pour cette recherche.</p>

    <ol v-else class="execution-panel__timeline">
      <template v-for="(group, groupIndex) in groups" :key="groupIndex">
        <li v-if="group.taskId" class="execution-panel__task-label">Tâche {{ group.taskId }}</li>
        <li v-for="event in group.events" :key="event.id" class="execution-panel__step">
          <span class="execution-panel__dot" aria-hidden="true" />
          <div class="execution-panel__step-body">
            <span class="execution-panel__label">{{ event.label }}</span>
            <span class="execution-panel__time">{{ formatTime(event.createdAt) }}</span>
          </div>
        </li>
      </template>
    </ol>
  </aside>
</template>

<style scoped>
.execution-panel {
  width: 320px;
  flex-shrink: 0;
  height: 100%;
  padding: 1.25rem;
  background: var(--background-alt-grey);
  border-left: 1px solid var(--border-default-grey);
  box-sizing: border-box;
  overflow-y: auto;
}

.execution-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.execution-panel__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.execution-panel__close {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-mention-grey);
}

.execution-panel__empty {
  margin-top: 1rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.execution-panel__error {
  margin-top: 1rem;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.execution-panel__timeline {
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.execution-panel__task-label {
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--text-mention-grey);
}

.execution-panel__step {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
}

.execution-panel__dot {
  flex-shrink: 0;
  margin-top: 0.35rem;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--background-action-high-blue-france);
}

.execution-panel__step-body {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border-default-grey);
  flex: 1;
}

.execution-panel__label {
  font-size: 0.875rem;
}

.execution-panel__time {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}
</style>
