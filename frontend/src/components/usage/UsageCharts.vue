<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Usage, UsageSums } from '../../types/usage'
import EnergyBatteries from './EnergyBatteries.vue'
import ExecutionPanel from './ExecutionPanel.vue'
import { STEP_LABELS } from './stepLabels'
import WaterBottles from './WaterBottles.vue'

const props = defineProps<{
  usage: Usage
  // Admin view only: the per-user list becomes a filter.
  selectedUser?: string | null
}>()

const emit = defineEmits<{
  selectUser: [userId: string | null]
}>()

const count = (value: number) => value.toLocaleString('fr-FR')
const compact = (value: number) =>
  new Intl.NumberFormat('fr-FR', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
const dayLabel = (day: string) =>
  new Date(`${day}T00:00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
const callsLabel = (calls: number) => `${count(calls)} appel${calls > 1 ? 's' : ''}`
const rowTitle = (label: string, row: UsageSums) =>
  `${label} : ${count(row.inputTokens)} entrée · ${count(row.outputTokens)} sortie · ${callsLabel(row.calls)}`

type Tab = 'tokens' | 'execution'
const tab = ref<Tab>('tokens')
const hasExecution = computed(() => props.usage.execution.byStep.length > 0)
const tabs = computed<{ id: Tab; label: string }[]>(() => [
  { id: 'tokens', label: 'Tokens' },
  ...(hasExecution.value ? [{ id: 'execution' as const, label: 'Temps, CPU et mémoire' }] : []),
])

const period = computed(() => (props.usage.days === 365 ? 'sur 1 an' : `sur ${props.usage.days} jours`))

// Every day of the period, those without a call at zero, so the bars keep a regular time axis.
const days = computed(() => {
  const byDay = new Map(props.usage.byDay.map((row) => [row.day, row]))
  const today = new Date()
  return Array.from({ length: props.usage.days }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (props.usage.days - 1 - index))
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    return byDay.get(day) ?? { day, inputTokens: 0, outputTokens: 0, totalTokens: 0, images: 0, pixels: 0, calls: 0 }
  })
})
const dayMax = computed(() => Math.max(1, ...days.value.map((row) => row.totalTokens)))
const hoveredDay = ref<(typeof days.value)[number] | null>(null)

interface Row extends UsageSums {
  key: string
  label: string
}

const stepRows = computed<Row[]>(() =>
  props.usage.byStep.map((row) => ({ ...row, key: row.step, label: STEP_LABELS[row.step] ?? row.step })),
)
const modelRows = computed<Row[]>(() =>
  props.usage.byModel.map((row) => ({ ...row, key: row.model, label: row.model })),
)
const userRows = computed<(Row & { userId: string | null })[]>(() =>
  props.usage.byUser.map((row) => ({
    ...row,
    key: row.userId ?? '',
    label: row.userId === null ? 'Non attribué (évaluations…)' : (row.display ?? row.userId),
  })),
)

function barWidth(row: UsageSums, rows: UsageSums[]) {
  return `${(row.totalTokens / Math.max(1, ...rows.map((item) => item.totalTokens))) * 100}%`
}
</script>

<template>
  <div class="usage-charts">
    <div class="usage-charts__stats">
      <div class="usage-charts__stat">
        <span class="usage-charts__stat-label">Tokens</span>
        <span class="usage-charts__stat-value">{{ count(usage.totals.totalTokens) }}</span>
      </div>
      <div class="usage-charts__stat">
        <span class="usage-charts__stat-label">Entrée (prompt)</span>
        <span class="usage-charts__stat-value">{{ count(usage.totals.inputTokens) }}</span>
      </div>
      <div class="usage-charts__stat">
        <span class="usage-charts__stat-label">Sortie (réponse)</span>
        <span class="usage-charts__stat-value">{{ count(usage.totals.outputTokens) }}</span>
      </div>
      <div class="usage-charts__stat">
        <span class="usage-charts__stat-label">Appels au modèle</span>
        <span class="usage-charts__stat-value">{{ count(usage.totals.calls) }}</span>
      </div>
      <div v-if="usage.totals.images > 0" class="usage-charts__stat">
        <span class="usage-charts__stat-label">Images générées</span>
        <span class="usage-charts__stat-value">{{ count(usage.totals.images) }}</span>
      </div>
      <div v-if="usage.routines.runs > 0" class="usage-charts__stat">
        <span class="usage-charts__stat-label">Routines : {{ count(usage.routines.runs) }} exécution{{ usage.routines.runs > 1 ? 's' : '' }}</span>
        <span class="usage-charts__stat-value">{{ count(usage.routines.totalTokens) }} jetons</span>
      </div>
    </div>

    <div class="usage-charts__impact">
      <WaterBottles :total-tokens="usage.totals.totalTokens" :period="period" />
      <EnergyBatteries v-if="hasExecution" :energy-wh="usage.execution.totals.energyWh" :period="period" />
    </div>

    <div v-if="tabs.length > 1" class="usage-charts__tabs" role="tablist" aria-label="Détail de la consommation">
      <button
        v-for="item in tabs"
        :id="`usage-tab-${item.id}`"
        :key="item.id"
        type="button"
        role="tab"
        class="usage-charts__tab"
        :class="{ 'usage-charts__tab--active': tab === item.id }"
        :aria-selected="tab === item.id"
        :aria-controls="`usage-panel-${item.id}`"
        @click="tab = item.id"
      >
        {{ item.label }}
      </button>
    </div>

    <div
      v-if="tab === 'tokens'"
      id="usage-panel-tokens"
      class="usage-charts__panel"
      role="tabpanel"
      aria-labelledby="usage-tab-tokens"
    >
      <section class="usage-charts__card">
        <div class="usage-charts__card-header">
          <h2 class="usage-charts__card-title">Par jour</h2>
          <ul class="usage-charts__legend" aria-label="Légende">
            <li><span class="usage-charts__swatch usage-charts__swatch--input" aria-hidden="true" />Entrée (prompt)</li>
            <li>
              <span class="usage-charts__swatch usage-charts__swatch--output" aria-hidden="true" />Sortie (réponse)
            </li>
          </ul>
        </div>
        <div class="usage-charts__day-info" aria-live="polite">
          <span>{{ hoveredDay ? dayLabel(hoveredDay.day) : period }}</span>
          <span>
            {{
              hoveredDay
                ? `${count(hoveredDay.inputTokens)} entrée · ${count(hoveredDay.outputTokens)} sortie · ${callsLabel(hoveredDay.calls)}`
                : `max ${compact(dayMax)} par jour`
            }}
          </span>
        </div>
        <div class="usage-charts__days" role="img" aria-label="Tokens consommés par jour">
          <div
            v-for="row in days"
            :key="row.day"
            class="usage-charts__day"
            :title="`${dayLabel(row.day)} : ${count(row.totalTokens)} tokens`"
            @mouseenter="hoveredDay = row"
            @mouseleave="hoveredDay = null"
          >
            <div class="usage-charts__bar--output" :style="{ height: `${(row.outputTokens / dayMax) * 100}%` }" />
            <div class="usage-charts__bar--input" :style="{ height: `${(row.inputTokens / dayMax) * 100}%` }" />
          </div>
        </div>
        <div class="usage-charts__axis">
          <span>{{ dayLabel(days[0].day) }}</span>
          <span>{{ dayLabel(days[days.length - 1].day) }}</span>
        </div>
      </section>

      <div class="usage-charts__split">
        <section class="usage-charts__card">
          <h2 class="usage-charts__card-title">Par étape</h2>
          <ul class="usage-charts__rows">
            <li v-for="row in stepRows" :key="row.key" class="usage-charts__row" :title="rowTitle(row.label, row)">
              <span class="usage-charts__row-head">
                <span class="usage-charts__row-label">{{ row.label }}</span>
                <span class="usage-charts__row-value">{{ count(row.totalTokens) }}</span>
              </span>
              <span class="usage-charts__row-bar" :style="{ width: barWidth(row, stepRows) }">
                <span class="usage-charts__bar--input" :style="{ flex: row.inputTokens }" />
                <span class="usage-charts__bar--output" :style="{ flex: row.outputTokens }" />
              </span>
            </li>
          </ul>
        </section>

        <section class="usage-charts__card">
          <h2 class="usage-charts__card-title">Par modèle</h2>
          <ul class="usage-charts__rows">
            <li v-for="row in modelRows" :key="row.key" class="usage-charts__row" :title="rowTitle(row.label, row)">
              <span class="usage-charts__row-head">
                <span class="usage-charts__row-label">{{ row.label }}</span>
                <span class="usage-charts__row-value">{{ count(row.totalTokens) }}</span>
              </span>
              <span class="usage-charts__row-bar" :style="{ width: barWidth(row, modelRows) }">
                <span class="usage-charts__bar--input" :style="{ flex: row.inputTokens }" />
                <span class="usage-charts__bar--output" :style="{ flex: row.outputTokens }" />
              </span>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <div
      v-else
      id="usage-panel-execution"
      class="usage-charts__panel"
      role="tabpanel"
      aria-labelledby="usage-tab-execution"
    >
      <ExecutionPanel :execution="usage.execution" :days="usage.days" />
    </div>

    <section v-if="userRows.length" class="usage-charts__card">
      <div class="usage-charts__card-header">
        <h2 class="usage-charts__card-title">Par utilisateur</h2>
        <button
          v-if="selectedUser !== undefined && selectedUser !== null"
          type="button"
          class="fr-btn fr-btn--sm fr-btn--tertiary-no-outline"
          @click="emit('selectUser', null)"
        >
          Voir tout le monde
        </button>
      </div>
      <p class="usage-charts__hint">Cliquez sur une personne pour n’afficher que sa consommation.</p>
      <ul class="usage-charts__rows">
        <li v-for="row in userRows" :key="row.key">
          <button
            type="button"
            class="usage-charts__row usage-charts__row--button"
            :class="{ 'usage-charts__row--selected': row.userId !== null && row.userId === selectedUser }"
            :aria-pressed="row.userId !== null && row.userId === selectedUser"
            :disabled="row.userId === null"
            :title="row.userId ? `${rowTitle(row.label, row)}\nuser_id : ${row.userId}` : rowTitle(row.label, row)"
            @click="row.userId && emit('selectUser', row.userId === selectedUser ? null : row.userId)"
          >
            <span class="usage-charts__row-head">
              <span class="usage-charts__row-label">{{ row.label }}</span>
              <span class="usage-charts__row-value">{{ count(row.totalTokens) }}</span>
            </span>
            <span class="usage-charts__row-bar" :style="{ width: barWidth(row, userRows) }">
              <span class="usage-charts__bar--input" :style="{ flex: row.inputTokens }" />
              <span class="usage-charts__bar--output" :style="{ flex: row.outputTokens }" />
            </span>
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.usage-charts {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.usage-charts__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0.75rem;
}

.usage-charts__stat,
.usage-charts__card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 1rem 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  min-width: 0;
}

.usage-charts__card {
  gap: 0.75rem;
}

.usage-charts__stat-label,
.usage-charts__day-info,
.usage-charts__axis,
.usage-charts__legend,
.usage-charts__hint {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.usage-charts__hint {
  margin: -0.5rem 0 0;
}

.usage-charts__stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.usage-charts__card-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.usage-charts__card-title {
  margin: 0;
  font-size: 1rem;
}

.usage-charts__legend {
  display: flex;
  gap: 1rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.usage-charts__legend li {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.usage-charts__swatch {
  width: 0.625rem;
  height: 0.625rem;
  border-radius: 0.125rem;
}

.usage-charts__swatch--input,
.usage-charts__bar--input {
  background: var(--background-action-high-blue-france);
}

.usage-charts__swatch--output,
.usage-charts__bar--output {
  background: var(--background-action-low-blue-france-hover, #b1b1f9);
}

.usage-charts__day-info,
.usage-charts__axis {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-variant-numeric: tabular-nums;
}

.usage-charts__days {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 11rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.usage-charts__day {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: flex-end;
  gap: 1px;
  min-width: 0;
  height: 100%;
}

.usage-charts__day:hover {
  background: var(--background-alt-grey);
}

.usage-charts__day .usage-charts__bar--output {
  border-radius: 0.125rem 0.125rem 0 0;
}

.usage-charts__impact {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr));
  gap: 1.25rem;
}

.usage-charts__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.usage-charts__tab {
  padding: 0.625rem 1rem;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  font: inherit;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.usage-charts__tab:hover {
  color: var(--text-default-grey);
}

.usage-charts__tab--active {
  border-bottom-color: var(--border-active-blue-france);
  color: var(--text-action-high-blue-france);
  font-weight: 600;
}

.usage-charts__panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.usage-charts__split {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
  gap: 1.25rem;
}

.usage-charts__rows {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.usage-charts__row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.375rem;
  border-radius: 0.375rem;
}

.usage-charts__row--button {
  width: 100%;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.usage-charts__row--button:hover:not(:disabled),
.usage-charts__row--selected {
  background: var(--background-alt-blue-france);
}

.usage-charts__row--button:disabled {
  cursor: default;
}

.usage-charts__row-head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.usage-charts__row-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-charts__row-value {
  flex-shrink: 0;
  color: var(--text-mention-grey);
  font-variant-numeric: tabular-nums;
}

.usage-charts__row-bar {
  display: flex;
  gap: 1px;
  height: 0.625rem;
  min-width: 2px;
  border-radius: 0.125rem;
  overflow: hidden;
}
</style>
