<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { browserTimezone, HALF_HOURS, INTERVALS, type RefreshSchedule, WEEKDAYS } from '../utils/refreshSchedule'

const props = defineProps<{
  // The schedule to start from (the document's current one); null: never.
  initial: RefreshSchedule | null
  idPrefix: string
}>()

// What the form describes - null for "Jamais" - and whether it can be saved as is.
const schedule = defineModel<RefreshSchedule | null>({ required: true })
const valid = defineModel<boolean>('valid', { default: true })

type Choice = 'never' | RefreshSchedule['kind']

const pad = (value: number) => String(value).padStart(2, '0')
const localDate = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const today = localDate(new Date())

// A single fetch's date and time, read back in the browser's time zone.
const initialRunAt = props.initial?.run_at ? new Date(props.initial.run_at) : null

const choice = ref<Choice>(props.initial?.kind ?? 'never')
const date = ref(initialRunAt ? localDate(initialRunAt) : today)
const runTime = ref(initialRunAt ? `${pad(initialRunAt.getHours())}:${pad(initialRunAt.getMinutes())}` : '09:00')
const timeOfDay = ref(props.initial?.time_of_day?.slice(0, 5) ?? '09:00')
const weekdays = ref<number[]>(props.initial?.weekdays ?? [0])
const intervalMinutes = ref(props.initial?.interval_minutes ?? 1440)

const runAt = computed(() => new Date(`${date.value}T${runTime.value}:00`))

const problem = computed(() => {
  if (choice.value === 'once' && !(runAt.value.getTime() > Date.now())) return 'Choisissez une date et une heure à venir.'
  if (choice.value === 'weekly' && weekdays.value.length === 0) return 'Choisissez au moins un jour.'
  return null
})

const built = computed<RefreshSchedule | null>(() => {
  const timezone = browserTimezone()
  switch (choice.value) {
    case 'never':
      return null
    case 'once':
      return { kind: 'once', run_at: runAt.value.toISOString(), timezone }
    case 'daily':
      return { kind: 'daily', time_of_day: timeOfDay.value, timezone }
    case 'weekly':
      return { kind: 'weekly', time_of_day: timeOfDay.value, weekdays: [...weekdays.value].sort(), timezone }
    case 'interval':
      return { kind: 'interval', interval_minutes: intervalMinutes.value, timezone }
  }
  return null
})

watch(
  [built, problem],
  () => {
    schedule.value = built.value
    valid.value = problem.value === null
  },
  { immediate: true },
)

function toggleDay(day: number) {
  weekdays.value = weekdays.value.includes(day)
    ? weekdays.value.filter((item) => item !== day)
    : [...weekdays.value, day]
}

const CHOICES: { value: Choice; label: string }[] = [
  { value: 'never', label: 'Jamais' },
  { value: 'once', label: 'Une fois' },
  { value: 'daily', label: 'Tous les jours' },
  { value: 'weekly', label: 'Certains jours de la semaine' },
  { value: 'interval', label: 'À intervalle régulier' },
]
</script>

<template>
  <fieldset class="refresh-form">
    <legend class="refresh-form__legend">Mise à jour automatique</legend>
    <div class="refresh-form__choices">
      <label v-for="option in CHOICES" :key="option.value" class="refresh-form__choice">
        <input v-model="choice" type="radio" :name="`${idPrefix}-kind`" :value="option.value" />
        {{ option.label }}
      </label>
    </div>

    <div v-if="choice === 'once'" class="refresh-form__row">
      <label :for="`${idPrefix}-date`">Le</label>
      <input :id="`${idPrefix}-date`" v-model="date" type="date" :min="today" />
      <label :for="`${idPrefix}-run-time`">à</label>
      <select :id="`${idPrefix}-run-time`" v-model="runTime">
        <option v-for="slot in HALF_HOURS" :key="slot" :value="slot">{{ slot }}</option>
      </select>
    </div>

    <div v-if="choice === 'weekly'" class="refresh-form__days" role="group" aria-label="Jours de la semaine">
      <button
        v-for="(day, index) in WEEKDAYS"
        :key="day"
        type="button"
        class="refresh-form__day"
        :class="{ 'refresh-form__day--on': weekdays.includes(index) }"
        :aria-pressed="weekdays.includes(index)"
        :title="day"
        @click="toggleDay(index)"
      >
        {{ day.slice(0, 3) }}
      </button>
    </div>

    <div v-if="choice === 'daily' || choice === 'weekly'" class="refresh-form__row">
      <label :for="`${idPrefix}-time`">À</label>
      <select :id="`${idPrefix}-time`" v-model="timeOfDay">
        <option v-for="slot in HALF_HOURS" :key="slot" :value="slot">{{ slot }}</option>
      </select>
    </div>

    <div v-if="choice === 'interval'" class="refresh-form__row">
      <label :for="`${idPrefix}-interval`">Toutes les</label>
      <select :id="`${idPrefix}-interval`" v-model.number="intervalMinutes">
        <option v-for="option in INTERVALS" :key="option.minutes" :value="option.minutes">{{ option.label }}</option>
      </select>
    </div>

    <p v-if="problem" class="refresh-form__problem">{{ problem }}</p>
    <p v-else-if="choice !== 'never'" class="refresh-form__hint">
      Si le contenu a changé, le document est entièrement réindexé (résumé, questions-réponses, entités, tags) ; sinon
      rien ne change.
    </p>
  </fieldset>
</template>

<style scoped>
.refresh-form {
  margin: 0;
  padding: 0;
  border: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.refresh-form__legend {
  margin-bottom: 0.25rem;
  font-size: 0.9375rem;
  font-weight: 600;
}

.refresh-form__choices {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
}

.refresh-form__choice {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.875rem;
}

.refresh-form__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.refresh-form__row input,
.refresh-form__row select {
  padding: 0.375rem 0.5rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.refresh-form__days {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.refresh-form__day {
  min-width: 2.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.8125rem;
  cursor: pointer;
}

.refresh-form__day--on {
  border-color: var(--border-active-blue-france);
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
}

.refresh-form__hint,
.refresh-form__problem {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.refresh-form__problem {
  color: var(--text-default-error);
}
</style>
