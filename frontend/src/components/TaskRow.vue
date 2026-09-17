<script setup lang="ts">
import { reactive } from 'vue'
import type { Task } from '../composables/useTasks'

const props = defineProps<{
  task: Task
  allTasks: Task[]
  depth: number
}>()

const emit = defineEmits<{
  revoke: [id: string]
  viewLogs: [task: Task]
}>()

const children = props.allTasks.filter((item) => item.parentId === props.task.id)

// A run's sliding-window steps (QA/entity extraction) can spawn dozens of
// sibling tasks - past this many, collapse them into one summary line
// instead of a wall of near-identical cards.
const GROUP_THRESHOLD = 4

interface ChildGroup {
  taskName: string
  items: Task[]
}

const groupsByTaskName = children.reduce<Record<string, ChildGroup>>((groups, child) => {
  const group = groups[child.taskName] ?? { taskName: child.taskName, items: [] }
  group.items.push(child)
  groups[child.taskName] = group
  return groups
}, {})
const childGroups: ChildGroup[] = Object.values(groupsByTaskName)

const expandedGroups = reactive(new Set<string>())
function toggleGroup(taskName: string) {
  if (expandedGroups.has(taskName)) expandedGroups.delete(taskName)
  else expandedGroups.add(taskName)
}

function groupSummary(items: Task[]): string {
  const counts = items.reduce<Record<string, number>>((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1
    return acc
  }, {})
  return Object.entries(counts)
    .map(([status, count]) => `${count} ${statusLabel(status).toLowerCase()}`)
    .join(', ')
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: 'En attente',
  STARTED: 'En cours',
  SUCCESS: 'Terminée',
  FAILURE: 'Échouée',
  REVOKED: 'Révoquée',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

function isRevocable(status: string): boolean {
  return status === 'PENDING' || status === 'STARTED'
}

const TASK_NAME_LABELS: Record<string, string> = {
  'app.tasks.process_document': 'Extraction du contenu',
  'app.tasks.chunk_document': 'Découpage (chunking)',
  'app.tasks.summarize_document': 'Résumé',
  'app.tasks.tag_document': 'Étiquetage (tagging)',
  'app.tasks.generate_qa_window': 'Génération de questions-réponses',
  'app.tasks.extract_entities_window': "Extraction d'entités/relations",
}

function taskLabel(taskName: string): string {
  return TASK_NAME_LABELS[taskName] ?? taskName
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <div class="task-row" :style="{ marginLeft: `${depth * 1.25}rem` }">
    <div class="task-row__card" :class="{ 'task-row__card--child': depth > 0 }">
      <div class="task-row__main">
        <span class="task-row__name">{{ taskLabel(task.taskName) }}</span>
        <span class="task-row__status" :class="`task-row__status--${task.status.toLowerCase()}`">
          {{ statusLabel(task.status) }}
        </span>
      </div>

      <p v-if="depth === 0 && (task.collectionName || task.documentName)" class="task-row__detail">
        <span v-if="task.collectionName">Collection : {{ task.collectionName }}</span>
        <span v-if="task.documentName">Document : {{ task.documentName }}</span>
      </p>

      <div class="task-row__footer">
        <span class="task-row__date">{{ formatDate(task.createdAt) }}</span>
        <div class="task-row__actions">
          <button type="button" class="task-row__link" @click="emit('viewLogs', task)">Voir les logs</button>
          <button
            v-if="isRevocable(task.status)"
            type="button"
            class="task-row__revoke"
            @click="emit('revoke', task.id)"
          >
            Révoquer
          </button>
        </div>
      </div>
    </div>

    <template v-for="group in childGroups" :key="group.taskName">
      <template v-if="group.items.length > GROUP_THRESHOLD && !expandedGroups.has(group.taskName)">
        <button
          type="button"
          class="task-row__group-toggle"
          :style="{ marginLeft: `${(depth + 1) * 1.25}rem` }"
          @click="toggleGroup(group.taskName)"
        >
          ▸ {{ taskLabel(group.taskName) }} — {{ group.items.length }} tâches ({{ groupSummary(group.items) }})
        </button>
      </template>
      <template v-else>
        <button
          v-if="group.items.length > GROUP_THRESHOLD"
          type="button"
          class="task-row__group-toggle"
          :style="{ marginLeft: `${(depth + 1) * 1.25}rem` }"
          @click="toggleGroup(group.taskName)"
        >
          ▾ {{ taskLabel(group.taskName) }} — {{ group.items.length }} tâches
        </button>
        <TaskRow
          v-for="child in group.items"
          :key="child.id"
          :task="child"
          :all-tasks="allTasks"
          :depth="depth + 1"
          @revoke="(id) => emit('revoke', id)"
          @view-logs="(t) => emit('viewLogs', t)"
        />
      </template>
    </template>
  </div>
</template>

<style scoped>
.task-row {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.task-row__card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.task-row__card--child {
  border-style: dashed;
  background: var(--background-alt-grey);
}

.task-row__main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.task-row__name {
  font-weight: 700;
}

.task-row__status {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.125rem 0.625rem;
  border-radius: 1rem;
  white-space: nowrap;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.task-row__status--started {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.task-row__status--success {
  background: var(--background-alt-green-emeraude, var(--background-alt-grey));
  color: var(--text-default-success, var(--text-default-grey));
}

.task-row__status--failure {
  background: var(--background-alt-red-marianne, var(--background-alt-grey));
  color: var(--text-default-error, var(--text-default-grey));
}

.task-row__detail {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
  margin: 0;
}

.task-row__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.task-row__date {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.task-row__actions {
  display: flex;
  gap: 0.5rem;
}

.task-row__link {
  border: none;
  background: transparent;
  color: var(--text-action-high-blue-france);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
}

.task-row__link:hover {
  text-decoration: underline;
}

.task-row__revoke {
  border: 1px solid var(--border-action-high-blue-france);
  background: transparent;
  color: var(--text-action-high-blue-france);
  border-radius: 0.25rem;
  padding: 0.25rem 0.75rem;
  font-size: 0.75rem;
  cursor: pointer;
}

.task-row__revoke:hover {
  background: var(--background-alt-blue-france);
}

.task-row__group-toggle {
  align-self: flex-start;
  border: 1px dashed var(--border-default-grey);
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
  border-radius: 0.5rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  cursor: pointer;
  text-align: left;
}

.task-row__group-toggle:hover {
  background: var(--background-alt-grey-hover);
}
</style>
