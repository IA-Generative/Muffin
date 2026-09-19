<script setup lang="ts">
import { computed } from 'vue'
import type { Task } from '../composables/useTasks'

const props = defineProps<{
  task: Task
  allTasks: Task[]
  depth: number
  expandedIds: Set<string>
}>()

const emit = defineEmits<{
  revoke: [id: string]
  viewLogs: [task: Task]
  toggleExpand: [id: string]
}>()

const children = computed(() => props.allTasks.filter((item) => item.parentId === props.task.id))
const isExpanded = computed(() => props.expandedIds.has(props.task.id))

const STATUS_LABELS: Record<string, string> = {
  PENDING: 'En attente',
  STARTED: 'En cours',
  SUCCESS: 'Terminée',
  FAILURE: 'Échouée',
  REVOKED: 'Révoquée',
}

const TASK_NAME_LABELS: Record<string, string> = {
  'app.tasks.process_document': 'Extraction',
  'app.tasks.chunk_document': 'Découpage',
  'app.tasks.summarize_document': 'Résumé',
  'app.tasks.tag_document': 'Étiquetage',
  'app.tasks.generate_qa_window': 'Q/R',
  'app.tasks.extract_entities_window': 'Entités',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

function taskLabel(taskName: string): string {
  return TASK_NAME_LABELS[taskName] ?? taskName
}

function isRevocable(status: string): boolean {
  return status === 'PENDING' || status === 'STARTED'
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <!-- Ligne de la tâche -->
  <tr class="task-row" :class="[`task-row--depth-${depth}`, { 'task-row--parent': children.length > 0 }]">
    <td class="task-row__cell task-row__expand">
      <button
        v-if="children.length > 0"
        type="button"
        class="task-row__toggle"
        :aria-expanded="isExpanded"
        @click="emit('toggleExpand', task.id)"
      >
        {{ isExpanded ? '▼' : '▶' }}
      </button>
    </td>
    <td class="task-row__cell task-row__name" :style="{ paddingLeft: `${depth * 1.5 + 0.75}rem` }">
      {{ taskLabel(task.taskName) }}
    </td>
    <td class="task-row__cell task-row__context">
      <span v-if="task.collectionName" class="task-row__context-item">{{ task.collectionName }}</span>
      <span v-if="task.documentName" class="task-row__context-item">{{ task.documentName }}</span>
    </td>
    <td class="task-row__cell task-row__status">
      <span class="task-row__status-badge" :class="`task-row__status--${task.status.toLowerCase()}`">
        {{ statusLabel(task.status) }}
      </span>
    </td>
    <td class="task-row__cell task-row__date">{{ formatDate(task.createdAt) }}</td>
    <td class="task-row__cell task-row__actions">
      <button type="button" class="task-row__link" @click="emit('viewLogs', task)">Logs</button>
      <button
        v-if="isRevocable(task.status)"
        type="button"
        class="task-row__revoke"
        @click="emit('revoke', task.id)"
      >
        Révoquer
      </button>
    </td>
  </tr>

  <!-- Lignes enfants (plates, indentées) -->
  <template v-if="isExpanded">
    <TaskTableRow
      v-for="child in children"
      :key="child.id"
      :task="child"
      :all-tasks="allTasks"
      :depth="depth + 1"
      :expanded-ids="expandedIds"
      @revoke="(id) => emit('revoke', id)"
      @view-logs="(t) => emit('viewLogs', t)"
      @toggle-expand="(id) => emit('toggleExpand', id)"
    />
  </template>
</template>

<style scoped>
.task-row {
  border-bottom: 1px solid #eee;
  transition: background-color 0.15s;
}

.task-row:hover {
  background-color: #f6f6f6;
}

.task-row--parent {
  background-color: #f9f9f9;
  font-weight: 500;
}

.task-row--depth-0 {
  border-top: 2px solid #ddd;
}

.task-row__cell {
  padding: 0.625rem 0.5rem;
  text-align: left;
  vertical-align: middle;
  font-size: 0.875rem;
}

.task-row__expand {
  width: 2.5rem;
  text-align: center;
}

.task-row__toggle {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.75rem;
  color: #666;
  padding: 0.25rem;
  border-radius: 4px;
  line-height: 1;
}

.task-row__toggle:hover {
  background-color: #e0e0e0;
}

.task-row__name {
  min-width: 10rem;
  color: #1a1a1a;
}

.task-row__context {
  max-width: 16rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-row__context-item {
  display: inline-block;
  margin-right: 0.5rem;
  color: #888;
  font-size: 0.8125rem;
}

.task-row__status-badge {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 10px;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.task-row__status--pending {
  background-color: #fff3cd;
  color: #856404;
}

.task-row__status--started {
  background-color: #cce5ff;
  color: #004085;
}

.task-row__status--success {
  background-color: #d4edda;
  color: #155724;
}

.task-row__status--failure {
  background-color: #f8d7da;
  color: #721c24;
}

.task-row__status--revoked {
  background-color: #e2e3e5;
  color: #383d41;
}

.task-row__date {
  white-space: nowrap;
  color: #888;
}

.task-row__actions {
  white-space: nowrap;
  text-align: right;
}

.task-row__link,
.task-row__revoke {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.8125rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}

.task-row__link {
  color: #0066cc;
}

.task-row__link:hover {
  background-color: #e6f0ff;
}

.task-row__revoke {
  color: #dc3545;
}

.task-row__revoke:hover {
  background-color: #ffe6e6;
}
</style>
