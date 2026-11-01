<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoutines } from '../composables/useRoutines'
import type { RoutineRun } from '../types/routine'
import { formatDateTime, formatDuration, runStatusLabel } from '../utils/routines'

const props = defineProps<{ routineId: string; refreshKey: number }>()

const { loadRuns } = useRoutines()
const runs = ref<RoutineRun[]>([])
const total = ref(0)
const page = ref(1)
const failed = ref(false)
const loading = ref(false)

async function load() {
  loading.value = true
  failed.value = false
  const result = await loadRuns(props.routineId, page.value)
  loading.value = false
  if (!result) {
    failed.value = true
    return
  }
  runs.value = page.value === 1 ? result.items : [...runs.value, ...result.items]
  total.value = result.total
}

function more() {
  page.value += 1
  void load()
}

onMounted(load)
// Une exécution lancée à la main ou une pause : l'historique repart du début.
watch(
  () => props.refreshKey,
  () => {
    page.value = 1
    void load()
  },
)
</script>

<template>
  <div class="routine-history">
    <p v-if="failed" class="routine-history__error" role="alert">Impossible de récupérer l’historique.</p>
    <p v-else-if="!runs.length && !loading" class="routine-history__empty">Aucune exécution pour le moment.</p>
    <table v-else class="routine-history__table">
      <caption class="fr-sr-only">Historique des exécutions</caption>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th scope="col">État</th>
          <th scope="col">Durée</th>
          <th scope="col">Jetons</th>
          <th scope="col">Conversation</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="run in runs" :key="run.id">
          <td>
            {{ formatDateTime(run.startedAt) }}
            <span v-if="run.trigger === 'manual'" class="routine-history__tag">à la main</span>
          </td>
          <td>
            <span :class="`routine-history__status routine-history__status--${run.status}`">{{ runStatusLabel(run.status, run.skipReason) }}</span>
            <span v-if="run.error" class="routine-history__detail">{{ run.error }}</span>
            <span v-if="run.note" class="routine-history__detail">{{ run.note }}</span>
          </td>
          <td>{{ formatDuration(run.durationSeconds) }}</td>
          <td>{{ run.status === 'skipped' ? '—' : run.totalTokens.toLocaleString('fr-FR') }}</td>
          <td>
            <router-link v-if="run.conversationId && run.status !== 'skipped'" :to="`/c/${run.conversationId}`">Ouvrir</router-link>
            <span v-else>—</span>
          </td>
        </tr>
      </tbody>
    </table>
    <button v-if="runs.length < total" type="button" class="fr-btn fr-btn--secondary fr-btn--sm" :disabled="loading" @click="more">
      Voir plus
    </button>
  </div>
</template>

<style scoped>
.routine-history {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow-x: auto;
}

.routine-history__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.routine-history__table th,
.routine-history__table td {
  padding: 0.375rem 0.5rem;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border-default-grey);
}

.routine-history__tag {
  margin-left: 0.375rem;
  padding: 0 0.375rem;
  border-radius: 0.25rem;
  background: var(--background-alt-grey);
  font-size: 0.6875rem;
}

.routine-history__status--succeeded {
  color: var(--text-default-success);
  font-weight: 600;
}

.routine-history__status--failed {
  color: var(--text-default-error);
  font-weight: 600;
}

.routine-history__detail {
  display: block;
  color: var(--text-mention-grey);
}

.routine-history__empty,
.routine-history__error {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.routine-history__error {
  color: var(--text-default-error);
}
</style>
