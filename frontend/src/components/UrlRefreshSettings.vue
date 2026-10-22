<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { describeSchedule, type RefreshSchedule } from '../utils/refreshSchedule'
import RefreshScheduleForm from './RefreshScheduleForm.vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const props = defineProps<{
  collectionId: string
  documentId: string
  // Only the collection owner can change it; everyone who can read the document sees it.
  editable: boolean
}>()

interface ScheduleOut {
  schedule: RefreshSchedule | null
  next_run_at: string | null
  last_fetched_at: string | null
}

const current = ref<ScheduleOut | null>(null)
// What the form holds - saved only on "Enregistrer", the form having several fields.
const draft = ref<RefreshSchedule | null>(null)
const valid = ref(true)
// Re-creates the form from what was saved.
const formKey = ref(0)
const busy = ref(false)
const error = ref<string | null>(null)

const url = computed(
  () => `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/refresh-schedule`,
)
const formatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
const changed = computed(() => JSON.stringify(comparable(draft.value)) !== JSON.stringify(comparable(current.value?.schedule ?? null)))

// The fields the form sets, without the time zone or a time's seconds the backend adds.
function comparable(schedule: RefreshSchedule | null) {
  if (!schedule) return null
  return {
    kind: schedule.kind,
    run_at: schedule.run_at ? new Date(schedule.run_at).getTime() : null,
    time_of_day: schedule.time_of_day?.slice(0, 5) ?? null,
    weekdays: schedule.weekdays ?? null,
    interval_minutes: schedule.interval_minutes ?? null,
  }
}

async function load() {
  try {
    const response = await fetch(url.value, { credentials: 'include' })
    if (response.ok) current.value = await response.json()
  } catch {
    // The setting just doesn't show; the document itself is unaffected.
  }
}

async function save() {
  busy.value = true
  error.value = null
  try {
    const response = await fetch(url.value, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule: draft.value }),
    })
    if (!response.ok) throw new Error(String(response.status))
    current.value = await response.json()
    formKey.value += 1
  } catch {
    error.value = 'La mise à jour automatique n’a pas pu être enregistrée.'
  } finally {
    busy.value = false
  }
}

// Fetching the page now: the worker reads it again, and reprocesses the document if it changed. Its
// date of last reading is then watched, to say when it is done.
const refreshing = ref(false)
const refreshMessage = ref<string | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | undefined
const REFRESH_POLL_MS = 3000
const REFRESH_POLL_TRIES = 40

function stopWatchingRefresh() {
  if (refreshTimer !== undefined) clearInterval(refreshTimer)
  refreshTimer = undefined
  refreshing.value = false
}

async function refreshNow() {
  refreshing.value = true
  refreshMessage.value = null
  error.value = null
  const fetchedBefore = current.value?.last_fetched_at ?? null
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/refresh`,
      { method: 'POST', credentials: 'include' },
    )
    if (!response.ok) {
      const detail = (await response.json().catch(() => null))?.detail
      throw new Error(detail?.message ?? 'La page n’a pas pu être relue.')
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'La page n’a pas pu être relue.'
    refreshing.value = false
    return
  }
  refreshMessage.value = 'Lecture de la page en cours…'
  let tries = 0
  refreshTimer = setInterval(async () => {
    await load()
    if ((current.value?.last_fetched_at ?? null) !== fetchedBefore) {
      refreshMessage.value = 'Page relue : le document est retraité si elle a changé.'
      stopWatchingRefresh()
    } else if (++tries >= REFRESH_POLL_TRIES) {
      refreshMessage.value = 'La lecture prend du temps : suivez-la dans les logs du document.'
      stopWatchingRefresh()
    }
  }, REFRESH_POLL_MS)
}

onMounted(load)
onUnmounted(stopWatchingRefresh)
</script>

<template>
  <section v-if="current" class="url-refresh">
    <template v-if="editable">
      <RefreshScheduleForm
        :key="formKey"
        v-model="draft"
        v-model:valid="valid"
        :initial="current.schedule"
        :id-prefix="`refresh-${documentId}`"
      />
      <button
        type="button"
        class="fr-btn fr-btn--secondary fr-btn--sm url-refresh__save"
        :disabled="busy || !valid || !changed"
        @click="save"
      >
        Enregistrer
      </button>
    </template>
    <template v-else>
      <h3 class="url-refresh__title">Mise à jour automatique</h3>
      <p class="url-refresh__line">{{ describeSchedule(current.schedule) }}</p>
    </template>
    <p v-if="current.last_fetched_at" class="url-refresh__line">
      Dernière lecture : {{ formatter.format(new Date(current.last_fetched_at)) }}
    </p>
    <p v-if="current.next_run_at" class="url-refresh__line">
      Prochaine vérification : {{ formatter.format(new Date(current.next_run_at)) }}
    </p>
    <button
      v-if="editable"
      type="button"
      class="fr-btn fr-btn--tertiary fr-btn--sm fr-icon-refresh-line fr-btn--icon-left url-refresh__now"
      :disabled="refreshing"
      @click="refreshNow"
    >
      Relire la page maintenant
    </button>
    <p v-if="refreshMessage" class="url-refresh__line" role="status">{{ refreshMessage }}</p>
    <p v-if="error" class="url-refresh__error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.url-refresh {
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-default-grey);
}

.url-refresh__title {
  margin: 0 0 0.5rem;
  font-size: 0.9375rem;
}

.url-refresh__save {
  margin-top: 0.75rem;
}

.url-refresh__now {
  margin-top: 0.75rem;
}

.url-refresh__line {
  margin: 0.375rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.url-refresh__error {
  margin: 0.375rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}
</style>
