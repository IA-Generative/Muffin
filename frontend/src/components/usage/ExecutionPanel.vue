<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Execution, ExecutionSums } from '../../types/usage'
import { formatBytes, formatDuration, formatEnergy } from '../../utils/execution'
import { STEP_LABELS } from './stepLabels'

const props = defineProps<{
  execution: Execution
  days: number
}>()

const count = (value: number) => value.toLocaleString('fr-FR')
const decimal = (value: number) => value.toLocaleString('fr-FR', { maximumFractionDigits: 3 })
const dayLabel = (day: string) =>
  new Date(`${day}T00:00:00`).toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'short',
  })
const details = (row: ExecutionSums) =>
  `${formatDuration(row.durationSeconds)} · CPU ${formatDuration(row.cpuSeconds)} · mémoire ${formatBytes(row.peakRssBytes)} · ${formatEnergy(row.energyWh)} · ${count(row.count)} exécution${row.count > 1 ? 's' : ''}`

// Every day of the period, those without a task at zero, so the bars keep a regular time axis.
const days = computed(() => {
  const byDay = new Map(props.execution.byDay.map((row) => [row.day, row]))
  const today = new Date()
  return Array.from({ length: props.days }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (props.days - 1 - index))
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    return (
      byDay.get(day) ?? {
        day,
        count: 0,
        durationSeconds: 0,
        cpuSeconds: 0,
        peakRssBytes: 0,
        energyWh: 0,
      }
    )
  })
})
const dayMax = computed(() => Math.max(1e-9, ...days.value.map((row) => row.energyWh)))
const hoveredDay = ref<(typeof days.value)[number] | null>(null)

const stepRows = computed(() =>
  props.execution.byStep.map((row) => ({
    ...row,
    key: `${row.kind}:${row.step}`,
    label: STEP_LABELS[row.step] ?? row.step,
  })),
)
const longest = computed(() => Math.max(1e-9, ...stepRows.value.map((row) => row.durationSeconds)))
</script>

<template>
  <section class="execution">
    <div class="execution__stats">
      <div class="execution__stat">
        <span class="execution__stat-label">Tâches exécutées</span>
        <span class="execution__stat-value">{{ count(execution.totals.count) }}</span>
      </div>
      <div class="execution__stat">
        <span class="execution__stat-label">Temps de traitement</span>
        <span class="execution__stat-value">{{ formatDuration(execution.totals.durationSeconds) }}</span>
      </div>
      <div class="execution__stat">
        <span class="execution__stat-label">Temps CPU</span>
        <span class="execution__stat-value">{{ formatDuration(execution.totals.cpuSeconds) }}</span>
      </div>
      <div class="execution__stat">
        <span class="execution__stat-label">Pic de mémoire (RAM)</span>
        <span class="execution__stat-value">{{ formatBytes(execution.totals.peakRssBytes) }}</span>
      </div>
      <div class="execution__stat">
        <span class="execution__stat-label">Énergie estimée</span>
        <span class="execution__stat-value">{{ formatEnergy(execution.totals.energyWh) }}</span>
      </div>
    </div>

    <div class="execution__card">
      <h3 class="execution__card-title">Énergie estimée par jour</h3>
      <div class="execution__day-info" aria-live="polite">
        <span>{{ hoveredDay ? dayLabel(hoveredDay.day) : `sur ${days.length} jours` }}</span>
        <span v-if="hoveredDay">{{ details(hoveredDay) }}</span>
      </div>
      <div class="execution__days" role="img" aria-label="Énergie estimée par jour">
        <div
          v-for="row in days"
          :key="row.day"
          class="execution__day"
          :title="`${dayLabel(row.day)} : ${formatEnergy(row.energyWh)}`"
          @mouseenter="hoveredDay = row"
          @mouseleave="hoveredDay = null"
        >
          <div class="execution__bar" :style="{ height: `${(row.energyWh / dayMax) * 100}%` }" />
        </div>
      </div>
    </div>

    <div class="execution__card">
      <h3 class="execution__card-title">Par tâche et par étape</h3>
      <ul class="execution__rows">
        <li v-for="row in stepRows" :key="row.key" class="execution__row" :title="details(row)">
          <span class="execution__row-head">
            <span class="execution__row-label">
              {{ row.label }}
              <span v-if="row.kind === 'node'" class="execution__chip">étape de l’agent</span>
            </span>
            <span class="execution__row-value">{{ formatDuration(row.durationSeconds) }}</span>
          </span>
          <span class="execution__row-bar" :style="{ width: `${(row.durationSeconds / longest) * 100}%` }" />
          <span class="execution__row-detail">
            CPU {{ formatDuration(row.cpuSeconds) }} · mémoire {{ formatBytes(row.peakRssBytes) }} ·
            {{ formatEnergy(row.energyWh) }}
          </span>
        </li>
      </ul>
    </div>

    <p class="execution__note">
      L’énergie est une estimation, pas une mesure :
      {{ decimal(execution.assumptions.wattsPerCore) }} W par cœur de CPU utilisé et
      {{ decimal(execution.assumptions.wattsPerGb) }} W par Go de mémoire occupé pendant la tâche, multipliés par le PUE
      du centre de données ({{ decimal(execution.assumptions.pue) }}). Elle ne comprend pas le calcul des modèles de
      langage, exécutés ailleurs. Les étapes de l’agent détaillent le temps d’une tâche : elles ne s’ajoutent pas à ses
      totaux, et ont leur énergie de calcul seulement, la mémoire étant comptée au niveau de la tâche.
    </p>
  </section>
</template>

<style scoped>
.execution {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.execution__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0.75rem;
}

.execution__stat,
.execution__card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 1rem 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  min-width: 0;
}

.execution__card {
  gap: 0.75rem;
}

.execution__stat-label,
.execution__day-info,
.execution__row-detail,
.execution__note {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.execution__stat-value {
  font-size: 1.5rem;
  font-weight: 700;
}

.execution__card-title {
  margin: 0;
  font-size: 1rem;
}

.execution__day-info {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  min-height: 1.25rem;
}

.execution__days {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 7rem;
}

.execution__day {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  min-width: 0;
}

.execution__bar {
  width: 100%;
  min-height: 1px;
  border-radius: 2px 2px 0 0;
  background: var(--background-action-high-blue-france);
}

.execution__rows {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.execution__row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.execution__row-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}

.execution__row-label {
  min-width: 0;
  overflow-wrap: anywhere;
}

.execution__chip {
  margin-left: 0.5rem;
  padding: 0 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 1rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  white-space: nowrap;
}

.execution__row-value {
  font-weight: 600;
  white-space: nowrap;
}

.execution__row-bar {
  display: block;
  height: 0.5rem;
  min-width: 2px;
  border-radius: 0.25rem;
  background: var(--background-action-high-blue-france);
}

.execution__note {
  margin: 0;
}
</style>
