<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const props = defineProps<{
  collectionId: string
  documentId: string
  // Only the collection owner can change it; everyone who can read the document sees it.
  editable: boolean
}>()

interface ScheduleOut {
  interval_minutes: number | null
  next_run_at: string | null
  last_fetched_at: string | null
}

// Multiples of the 30-minute scan that looks for documents due (see the backend's
// REFRESH_INTERVALS_MINUTES): anything shorter couldn't be honoured.
const OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: 'Jamais' },
  { value: 30, label: 'Toutes les 30 minutes' },
  { value: 60, label: 'Toutes les heures' },
  { value: 360, label: 'Toutes les 6 heures' },
  { value: 720, label: 'Toutes les 12 heures' },
  { value: 1440, label: 'Tous les jours' },
  { value: 10080, label: 'Toutes les semaines' },
]

const schedule = ref<ScheduleOut | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)

const url = computed(
  () => `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/refresh-schedule`,
)
const formatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })
const label = computed(() => OPTIONS.find((option) => option.value === schedule.value?.interval_minutes)?.label)

async function load() {
  try {
    const response = await fetch(url.value, { credentials: 'include' })
    if (response.ok) schedule.value = await response.json()
  } catch {
    // The setting just doesn't show; the document itself is unaffected.
  }
}

async function change(event: Event) {
  const raw = (event.target as HTMLSelectElement).value
  busy.value = true
  error.value = null
  try {
    const response = await fetch(url.value, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interval_minutes: raw === '' ? null : Number(raw) }),
    })
    if (!response.ok) throw new Error(String(response.status))
    schedule.value = await response.json()
  } catch {
    error.value = 'La fréquence n’a pas pu être enregistrée.'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-if="schedule" class="url-refresh">
    <h3 class="url-refresh__title">Mise à jour automatique</h3>
    <select
      v-if="editable"
      class="fr-select url-refresh__select"
      aria-label="Fréquence de mise à jour de la page"
      :value="schedule.interval_minutes ?? ''"
      :disabled="busy"
      @change="change"
    >
      <option v-for="option in OPTIONS" :key="option.label" :value="option.value ?? ''">{{ option.label }}</option>
    </select>
    <p v-else class="url-refresh__line">{{ label }}</p>
    <p class="url-refresh__hint">
      La page est relue à cette fréquence. Si son contenu a changé, le document est entièrement réindexé (résumé,
      questions-réponses, entités, tags) ; sinon rien ne change.
    </p>
    <p v-if="schedule.last_fetched_at" class="url-refresh__line">
      Dernière lecture : {{ formatter.format(new Date(schedule.last_fetched_at)) }}
    </p>
    <p v-if="schedule.next_run_at" class="url-refresh__line">
      Prochaine vérification : vers {{ formatter.format(new Date(schedule.next_run_at)) }}
    </p>
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

.url-refresh__select {
  max-width: 18rem;
}

.url-refresh__hint,
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
