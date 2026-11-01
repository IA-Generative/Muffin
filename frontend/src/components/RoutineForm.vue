<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAssistants } from '../composables/useAssistants'
import { useCollections } from '../composables/useCollections'
import { useRoutines } from '../composables/useRoutines'
import type { Routine, RoutineDraft, RoutineKind } from '../types/routine'
import { collectionPathLabel } from '../utils/collectionPath'
import { WEEKDAYS, emptyDraft, formatDateTime, scheduleProblem, shortTime } from '../utils/routines'

const props = defineProps<{ routine: Routine | null }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()

const { status, save, preview } = useRoutines()
const { collections, refresh: refreshCollections } = useCollections()
const { assistants, refreshAssistants } = useAssistants()

const draft = reactive<RoutineDraft>(emptyDraft())
// L'intervalle se saisit en heures ou en jours ; le serveur compte en minutes.
const intervalValue = ref(2)
const intervalUnit = ref<'hours' | 'days'>('hours')
const collectionSearch = ref('')
const message = ref<string | null>(null)
const saving = ref(false)
const upcoming = ref<string[]>([])
const previewMessage = ref<string | null>(null)

onMounted(() => {
  if (!collections.value.length) void refreshCollections()
  if (!assistants.value.length) void refreshAssistants()
})

watch(
  () => props.routine,
  (routine) => {
    Object.assign(draft, emptyDraft())
    if (routine) {
      Object.assign(draft, {
        name: routine.name,
        question: routine.question,
        collectionIds: [...routine.collectionIds],
        includeDescendants: routine.includeDescendants,
        assistantId: routine.assistantId,
        webSearch: routine.webSearch,
        schedule: { ...routine.schedule, weekdays: routine.schedule.weekdays ? [...routine.schedule.weekdays] : null },
        condition: routine.condition,
        resultMode: routine.resultMode,
        notify: routine.notify,
      })
      const minutes = routine.schedule.intervalMinutes ?? 0
      if (minutes && minutes % 1440 === 0) {
        intervalUnit.value = 'days'
        intervalValue.value = minutes / 1440
      } else {
        intervalUnit.value = 'hours'
        intervalValue.value = minutes ? minutes / 60 : 2
      }
    }
  },
  { immediate: true },
)

const KINDS: { value: RoutineKind; label: string }[] = [
  { value: 'interval', label: 'Toutes les…' },
  { value: 'daily', label: 'Tous les jours' },
  { value: 'weekly', label: 'Certains jours de la semaine' },
  { value: 'monthly', label: 'Une fois par mois' },
]

const minInterval = computed(() => status.value?.minIntervalMinutes ?? 60)

// Le rythme tel que le serveur le comprend, mis à jour à chaque saisie.
const schedule = computed(() => ({
  ...draft.schedule,
  intervalMinutes:
    draft.schedule.kind === 'interval'
      ? Math.round((intervalValue.value || 0) * (intervalUnit.value === 'days' ? 1440 : 60))
      : null,
}))
const problem = computed(() => scheduleProblem(schedule.value, minInterval.value))

let previewTimer: ReturnType<typeof setTimeout> | undefined
watch(
  schedule,
  (value) => {
    clearTimeout(previewTimer)
    upcoming.value = []
    previewMessage.value = null
    if (scheduleProblem(value, minInterval.value)) return
    previewTimer = setTimeout(async () => {
      const result = await preview(value)
      upcoming.value = result.dates
      previewMessage.value = result.message
    }, 300)
  },
  { immediate: true, deep: true },
)

const filteredCollections = computed(() => {
  const query = collectionSearch.value.trim().toLowerCase()
  return collections.value
    .map((collection) => ({ id: collection.id, label: collectionPathLabel(collection) }))
    .filter((collection) => collection.label.toLowerCase().includes(query))
    .sort((a, b) => a.label.localeCompare(b.label))
})

function toggleCollection(id: string) {
  draft.collectionIds = draft.collectionIds.includes(id)
    ? draft.collectionIds.filter((existing) => existing !== id)
    : [...draft.collectionIds, id]
}

function toggleWeekday(day: number) {
  const days = draft.schedule.weekdays ?? []
  draft.schedule.weekdays = days.includes(day) ? days.filter((existing) => existing !== day) : [...days, day]
}

const lacksScope = computed(
  () => draft.condition === 'only_if_new' && !draft.collectionIds.length && !draft.assistantId,
)
const canSave = computed(
  () => !!draft.name.trim() && !!draft.question.trim() && !problem.value && !lacksScope.value && !saving.value,
)

async function submit() {
  if (!canSave.value) return
  saving.value = true
  message.value = null
  draft.schedule = { ...schedule.value }
  const refusal = await save(draft, props.routine?.id)
  saving.value = false
  if (refusal) message.value = refusal
  else emit('saved')
}
</script>

<template>
  <form class="routine-form" @submit.prevent="submit">
    <h2 class="routine-form__title">{{ routine ? 'Modifier la routine' : 'Nouvelle routine' }}</h2>

    <div class="routine-form__field">
      <label for="routine-name">Nom</label>
      <input id="routine-name" v-model="draft.name" class="fr-input" type="text" maxlength="200" required />
    </div>

    <div class="routine-form__field">
      <label for="routine-question">Question posée à l’agent</label>
      <textarea
        id="routine-question"
        v-model="draft.question"
        class="fr-input"
        rows="3"
        maxlength="4000"
        required
        aria-describedby="routine-question-hint"
      />
      <p id="routine-question-hint" class="routine-form__hint">
        Comme un message du chat : « Qu’est-ce qui a changé cette semaine dans les règlements ? ». La routine lit vos
        collections (et le web si vous l’autorisez) ; elle n’utilise aucun outil qui agit en votre nom.
      </p>
    </div>

    <fieldset class="routine-form__field">
      <legend>Sur quoi porte-t-elle ?</legend>
      <div class="routine-form__field">
        <label for="routine-assistant">Assistant (facultatif)</label>
        <select id="routine-assistant" v-model="draft.assistantId" class="fr-select">
          <option :value="null">Aucun : les collections choisies ci-dessous</option>
          <option v-for="assistant in assistants" :key="assistant.id" :value="assistant.id">{{ assistant.name }}</option>
        </select>
      </div>
      <template v-if="!draft.assistantId">
        <label class="routine-form__sub" for="routine-collection-search">Collections</label>
        <input id="routine-collection-search" v-model="collectionSearch" class="fr-input" type="search" placeholder="Filtrer les collections" />
        <ul class="routine-form__collections">
          <li v-for="collection in filteredCollections" :key="collection.id" class="fr-checkbox-group">
            <input :id="`routine-collection-${collection.id}`" type="checkbox" :checked="draft.collectionIds.includes(collection.id)" @change="toggleCollection(collection.id)" />
            <label class="fr-label" :for="`routine-collection-${collection.id}`">{{ collection.label }}</label>
          </li>
        </ul>
        <p class="routine-form__hint">Aucune collection choisie : tout ce que vous pouvez lire, comme dans le chat.</p>
        <div class="fr-checkbox-group">
          <input id="routine-descendants" v-model="draft.includeDescendants" type="checkbox" />
          <label class="fr-label" for="routine-descendants">Inclure les sous-collections</label>
        </div>
      </template>
      <div class="fr-checkbox-group">
        <input id="routine-web" v-model="draft.webSearch" type="checkbox" />
        <label class="fr-label" for="routine-web">
          Autoriser la recherche sur le web
          <span class="fr-hint-text">Désactivée par défaut : la question part alors vers un moteur de recherche.</span>
        </label>
      </div>
    </fieldset>

    <fieldset class="routine-form__field">
      <legend>Rythme</legend>
      <div class="routine-form__row">
        <div class="routine-form__field">
          <label for="routine-kind">Quand</label>
          <select id="routine-kind" v-model="draft.schedule.kind" class="fr-select">
            <option v-for="kind in KINDS" :key="kind.value" :value="kind.value">{{ kind.label }}</option>
          </select>
        </div>
        <template v-if="draft.schedule.kind === 'interval'">
          <div class="routine-form__field">
            <label for="routine-interval">Intervalle</label>
            <input id="routine-interval" v-model.number="intervalValue" class="fr-input" type="number" min="1" step="1" />
          </div>
          <div class="routine-form__field">
            <label for="routine-unit">Unité</label>
            <select id="routine-unit" v-model="intervalUnit" class="fr-select">
              <option value="hours">heures</option>
              <option value="days">jours</option>
            </select>
          </div>
        </template>
        <div v-else class="routine-form__field">
          <label for="routine-time">À</label>
          <input
            id="routine-time"
            :value="shortTime(draft.schedule.timeOfDay)"
            class="fr-input"
            type="time"
            @input="draft.schedule.timeOfDay = ($event.target as HTMLInputElement).value"
          />
        </div>
        <div v-if="draft.schedule.kind === 'monthly'" class="routine-form__field">
          <label for="routine-day">Le</label>
          <input id="routine-day" v-model.number="draft.schedule.dayOfMonth" class="fr-input" type="number" min="1" max="31" />
        </div>
      </div>
      <div v-if="draft.schedule.kind === 'weekly'" class="routine-form__days" role="group" aria-label="Jours de la semaine">
        <div v-for="(name, day) in WEEKDAYS" :key="name" class="fr-checkbox-group">
          <input :id="`routine-day-${day}`" type="checkbox" :checked="draft.schedule.weekdays?.includes(day)" @change="toggleWeekday(day)" />
          <label class="fr-label" :for="`routine-day-${day}`">{{ name }}</label>
        </div>
      </div>
      <p class="routine-form__hint">
        Fuseau horaire : {{ draft.schedule.timezone }}. L’heure reste la même malgré le changement d’heure. Intervalle
        minimal : {{ minInterval }} minutes.
      </p>
      <p v-if="problem" class="routine-form__error" role="alert">{{ problem }}</p>
      <p v-else-if="previewMessage" class="routine-form__error" role="alert">{{ previewMessage }}</p>
      <div v-else-if="upcoming.length" class="routine-form__preview" aria-live="polite">
        <strong>Prochaines dates</strong>
        <ol>
          <li v-for="date in upcoming" :key="date">{{ formatDateTime(date, draft.schedule.timezone) }}</li>
        </ol>
      </div>
    </fieldset>

    <fieldset class="routine-form__field">
      <legend>Condition</legend>
      <div class="fr-radio-group">
        <input id="routine-cond-always" v-model="draft.condition" type="radio" value="always" />
        <label class="fr-label" for="routine-cond-always">Toujours</label>
      </div>
      <div class="fr-radio-group">
        <input id="routine-cond-new" v-model="draft.condition" type="radio" value="only_if_new" />
        <label class="fr-label" for="routine-cond-new">
          Seulement s’il y a du nouveau
          <span class="fr-hint-text">Rien n’est demandé à l’agent (donc rien n’est consommé) si aucun document des collections n’a été ajouté ou modifié.</span>
        </label>
      </div>
      <p v-if="lacksScope" class="routine-form__error" role="alert">Choisissez des collections ou un assistant pour cette condition.</p>
    </fieldset>

    <fieldset class="routine-form__field">
      <legend>Résultat</legend>
      <div class="fr-radio-group">
        <input id="routine-result-new" v-model="draft.resultMode" type="radio" value="new_conversation" />
        <label class="fr-label" for="routine-result-new">Une nouvelle conversation à chaque exécution</label>
      </div>
      <div class="fr-radio-group">
        <input id="routine-result-single" v-model="draft.resultMode" type="radio" value="single_conversation" />
        <label class="fr-label" for="routine-result-single">Une seule conversation pour toute la routine</label>
      </div>
    </fieldset>

    <div class="routine-form__field">
      <label for="routine-notify">Me prévenir</label>
      <select id="routine-notify" v-model="draft.notify" class="fr-select" aria-describedby="routine-notify-hint">
        <option value="always">À chaque exécution</option>
        <option value="failure">Seulement en cas d’échec</option>
        <option value="never">Jamais</option>
      </select>
      <p id="routine-notify-hint" class="routine-form__hint">Dans l’application, par la cloche. Le courriel n’est pas encore proposé.</p>
    </div>

    <p v-if="message" class="routine-form__error" role="alert">{{ message }}</p>
    <div class="routine-form__actions">
      <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
      <button type="submit" class="fr-btn" :disabled="!canSave">{{ saving ? 'Enregistrement…' : 'Enregistrer' }}</button>
    </div>
  </form>
</template>

<style scoped>
.routine-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.routine-form__title {
  margin: 0;
  font-size: 1.125rem;
}

.routine-form__field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  border: none;
  padding: 0;
  margin: 0;
  min-width: 0;
}

.routine-form__field > label,
.routine-form__field > legend,
fieldset.routine-form__field > legend {
  font-size: 0.875rem;
  font-weight: 700;
}

.routine-form__sub {
  font-size: 0.875rem;
  font-weight: 700;
}

.routine-form__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.routine-form__row > .routine-form__field {
  flex: 1;
  min-width: 9rem;
}

.routine-form__days {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
}

.routine-form__collections {
  margin: 0;
  padding: 0.5rem;
  max-height: 12rem;
  overflow-y: auto;
  list-style: none;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.routine-form__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.routine-form__error {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.routine-form__preview {
  font-size: 0.875rem;
}

.routine-form__preview ol {
  margin: 0.25rem 0 0;
  padding-left: 1.25rem;
}

.routine-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
</style>
