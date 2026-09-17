<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useTasks, type Task } from '../composables/useTasks'
import PaginationControls from './PaginationControls.vue'
import TaskRow from './TaskRow.vue'

const { tasks, isLoading, error, page, pageCount, fetchTasks, revokeTask, fetchTaskLogs } = useTasks()
onMounted(fetchTasks)
watch(page, fetchTasks)

const rootTasks = () => tasks.value.filter((task) => task.parentId === null)

const logsTask = ref<Task | null>(null)
const logsContent = ref('')
const logsLoading = ref(false)

async function openLogs(task: Task) {
  logsTask.value = task
  logsLoading.value = true
  try {
    logsContent.value = await fetchTaskLogs(task.id)
  } catch {
    logsContent.value = 'Impossible de récupérer les logs.'
  } finally {
    logsLoading.value = false
  }
}

function closeLogs() {
  logsTask.value = null
  logsContent.value = ''
}
</script>

<template>
  <section class="tasks-view">
    <div class="tasks-view__header">
      <h1>Tâches</h1>
      <button type="button" class="fr-btn fr-btn--secondary" @click="fetchTasks">Actualiser</button>
    </div>
    <p class="tasks-view__intro">
      Suivez l'avancement des traitements lancés en arrière-plan (extraction, découpage, résumé, étiquetage,
      questions-réponses, extraction d'entités) et révoquez ceux encore en attente ou en cours.
    </p>

    <p v-if="error" class="tasks-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading" class="tasks-view__empty">Chargement des tâches…</p>
    <p v-else-if="tasks.length === 0" class="tasks-view__empty">Aucune tâche pour le moment.</p>

    <div v-else class="tasks-view__runs">
      <TaskRow
        v-for="root in rootTasks()"
        :key="root.id"
        :task="root"
        :all-tasks="tasks"
        :depth="0"
        @revoke="revokeTask"
        @view-logs="openLogs"
      />
    </div>

    <PaginationControls v-if="tasks.length > 0" v-model:page="page" :page-count="pageCount" />

    <div v-if="logsTask" class="logs-overlay" @click.self="closeLogs">
      <div class="logs-modal" role="dialog" aria-modal="true">
        <div class="logs-modal__header">
          <h2>Logs</h2>
          <button type="button" class="logs-modal__close" aria-label="Fermer" @click="closeLogs">✕</button>
        </div>
        <p v-if="logsLoading" class="tasks-view__empty">Chargement…</p>
        <pre v-else class="logs-modal__content">{{ logsContent || 'Aucun log pour cette tâche.' }}</pre>
      </div>
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

.tasks-view__runs {
  max-width: 72rem;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
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
  max-width: 48rem;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.logs-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.logs-modal__header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.logs-modal__close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-mention-grey);
}

.logs-modal__content {
  flex: 1;
  overflow-y: auto;
  margin: 0;
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
  font-size: 0.8125rem;
  font-family: ui-monospace, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
