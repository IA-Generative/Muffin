<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useTasks } from '../composables/useTasks'
import PaginationControls from './PaginationControls.vue'
import TaskLogViewer from './TaskLogViewer.vue'
import TaskTableRow from './TaskTableRow.vue'

const { tasks, isLoading, error, page, pageCount, totalTasks, fetchTasks, revokeTask } = useTasks()
onMounted(() => fetchTasks())
watch(page, () => fetchTasks())

const rootTasks = () => tasks.value.filter((task) => task.parentId === null)

const expandedTasks = reactive(new Set<string>())

function toggleExpand(taskId: string) {
  if (expandedTasks.has(taskId)) {
    expandedTasks.delete(taskId)
  } else {
    expandedTasks.add(taskId)
  }
}

// The task whose logs are open - looked up in the list, so that its status follows the refreshes.
const logsTaskId = ref<string | null>(null)
const logsTask = computed(() => tasks.value.find((task) => task.id === logsTaskId.value) ?? null)
const logsLive = computed(() => logsTask.value?.status === 'PENDING' || logsTask.value?.status === 'STARTED')

// While its logs are followed live, the task's status is refreshed too: they stop with it.
let statusTimer: ReturnType<typeof setInterval> | undefined
watch(logsLive, (live) => {
  if (statusTimer !== undefined) clearInterval(statusTimer)
  statusTimer = live ? setInterval(() => fetchTasks({ quiet: true }), 5000) : undefined
})
onUnmounted(() => clearInterval(statusTimer))

function openLogs(task: { id: string }) {
  logsTaskId.value = task.id
}

function closeLogs() {
  logsTaskId.value = null
}
</script>

<template>
  <section class="tasks-view">
    <div class="tasks-view__header">
      <h1>Tâches</h1>
      <button type="button" class="fr-btn fr-btn--secondary" @click="fetchTasks()">Actualiser</button>
    </div>
    <p class="tasks-view__intro">
      Suivez l'avancement des traitements lancés en arrière-plan (extraction, découpage, résumé, étiquetage,
      questions-réponses, extraction d'entités) et révoquez ceux encore en attente ou en cours.
    </p>

    <p v-if="error" class="tasks-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading" class="tasks-view__empty">Chargement des tâches…</p>
    <p v-else-if="tasks.length === 0" class="tasks-view__empty">Aucune tâche pour le moment.</p>

    <div v-else class="tasks-view__table-container">
      <p class="tasks-view__count">{{ totalTasks }} tâche{{ totalTasks > 1 ? 's' : '' }}</p>
      <table class="tasks-view__table">
        <thead>
          <tr>
            <th scope="col" class="tasks-view__th tasks-view__th--expand"></th>
            <th scope="col" class="tasks-view__th tasks-view__th--name">Tâche</th>
            <th scope="col" class="tasks-view__th tasks-view__th--context">Contexte</th>
            <th scope="col" class="tasks-view__th tasks-view__th--status">Statut</th>
            <th scope="col" class="tasks-view__th tasks-view__th--date">Créée le</th>
            <th scope="col" class="tasks-view__th tasks-view__th--actions">Actions</th>
          </tr>
        </thead>
        <tbody>
          <TaskTableRow
            v-for="root in rootTasks()"
            :key="root.id"
            :task="root"
            :all-tasks="tasks"
            :depth="0"
            :expanded-ids="expandedTasks"
            @revoke="revokeTask"
            @view-logs="openLogs"
            @toggle-expand="toggleExpand"
          />
        </tbody>
      </table>
    </div>

    <PaginationControls v-if="tasks.length > 0" v-model:page="page" :page-count="pageCount" />

    <div v-if="logsTask" class="logs-overlay" @click.self="closeLogs">
      <dialog class="logs-modal" open>
        <div class="logs-modal__header">
          <h2>Logs — {{ logsTask.taskName }}</h2>
          <button type="button" class="logs-modal__close" aria-label="Fermer" @click="closeLogs">✕</button>
        </div>
        <TaskLogViewer :path="`/api/tasks/${logsTask.id}/logs`" :live="logsLive" />
      </dialog>
    </div>
  </section>
</template>

<style scoped>
.tasks-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.tasks-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 72rem;
  margin: 0 auto;
}

.tasks-view__header h1 {
  margin: 0;
}

.tasks-view__intro {
  max-width: 72rem;
  margin: 0.5rem auto 1.5rem;
  color: var(--text-mention-grey);
}

.tasks-view__empty,
.tasks-view__error {
  max-width: 72rem;
  margin: 3rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.tasks-view__error {
  color: var(--text-default-error);
}

.tasks-view__table-container {
  max-width: 72rem;
  margin: 0 auto;
  overflow-x: auto;
}

.tasks-view__count {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.tasks-view__table {
  width: 100%;
  border-collapse: collapse;
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  border-radius: 8px;
  overflow: hidden;
}

.tasks-view__th {
  padding: 0.875rem 0.5rem;
  text-align: left;
  font-weight: 600;
  color: #555;
  border-bottom: 2px solid #e0e0e0;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background-color: #fafafa;
}

.tasks-view__th--expand {
  width: 2.5rem;
}

.tasks-view__th--name {
  min-width: 10rem;
}

.tasks-view__th--context {
  width: 16rem;
}

.tasks-view__th--status {
  width: 8rem;
}

.tasks-view__th--date {
  width: 10rem;
}

.tasks-view__th--actions {
  width: 8rem;
  text-align: right;
}

.logs-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.logs-modal {
  width: 100%;
  max-width: 64rem;
  height: 80vh;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey, white);
  color: var(--text-default-grey, #333);
  border: none;
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.logs-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.logs-modal__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.logs-modal__close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-mention-grey, #888);
}
</style>
