<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoutines } from '../composables/useRoutines'
import type { Routine } from '../types/routine'
import { describeSchedule, formatDateTime, runStatusLabel, stateLabel } from '../utils/routines'
import RoutineForm from './RoutineForm.vue'
import RoutineHistory from './RoutineHistory.vue'

const { routines, status, isLoading, error, loadRoutines, pause, resume, remove, runNow } = useRoutines()

const editing = ref<Routine | null>(null)
const showForm = ref(false)
const openHistory = ref<string | null>(null)
const historyKey = ref(0)
const notice = ref<string | null>(null)
const busy = ref<string | null>(null)

onMounted(loadRoutines)

const enabled = computed(() => status.value?.enabled ?? true)
const canCreate = computed(
  () => enabled.value && (status.value ? status.value.active < status.value.maxActive : true),
)

function startCreate() {
  editing.value = null
  showForm.value = true
  notice.value = null
}

function startEdit(routine: Routine) {
  editing.value = routine
  showForm.value = true
  notice.value = null
}

function saved() {
  showForm.value = false
  historyKey.value += 1
}

async function toggle(routine: Routine) {
  busy.value = routine.id
  const message = await (routine.state === 'active' ? pause(routine.id) : resume(routine.id))
  notice.value = message
  busy.value = null
  historyKey.value += 1
}

async function run(routine: Routine) {
  busy.value = routine.id
  notice.value = null
  const result = await runNow(routine.id)
  busy.value = null
  if (result.message) notice.value = result.message
  else if (result.run?.status === 'skipped') notice.value = `Pas lancée : ${runStatusLabel('skipped', result.run.skipReason).toLowerCase()}.`
  else notice.value = 'La routine est lancée. Vous serez prévenu quand le résultat est prêt.'
  historyKey.value += 1
}

async function destroy(routine: Routine) {
  if (!window.confirm(`Supprimer la routine « ${routine.name} » et son historique ? Les conversations déjà produites restent.`)) return
  notice.value = await remove(routine.id)
}
</script>

<template>
  <section class="routines">
    <div class="routines__header">
      <h1>Routines</h1>
      <button type="button" class="fr-btn" :disabled="!canCreate || showForm" @click="startCreate">Nouvelle routine</button>
    </div>
    <p class="routines__intro">
      Une question posée à l’agent à intervalles réguliers, sans que vous ouvriez le chat : « chaque lundi, qu’est-ce qui a
      changé dans la collection Règlements ? ». Chaque exécution produit une conversation que vous pouvez ouvrir et
      poursuivre, et vous en êtes prévenu par la cloche. Une routine agit avec vos droits <em>au moment où elle
      s’exécute</em>, en lecture seule.
    </p>

    <p v-if="status && !status.enabled" class="routines__notice routines__notice--off" role="status">
      Les routines ne sont pas activées par votre administrateur. Vos routines existantes ne s’exécutent pas pour le moment.
    </p>
    <p v-else-if="status" class="routines__limits">
      {{ status.active }} routine{{ status.active > 1 ? 's' : '' }} active{{ status.active > 1 ? 's' : '' }} sur
      {{ status.maxActive }} permises · {{ status.runsToday }} exécution{{ status.runsToday > 1 ? 's' : '' }} sur
      {{ status.maxRunsPerDay }} ces dernières 24 h · intervalle minimal {{ status.minIntervalMinutes }} minutes.
    </p>
    <p v-if="notice" class="routines__notice" role="status">{{ notice }}</p>
    <p v-if="error" class="routines__notice routines__notice--error" role="alert">{{ error }}</p>

    <RoutineForm v-if="showForm" :routine="editing" @saved="saved" @cancel="showForm = false" />

    <p v-if="isLoading && !routines.length" class="routines__empty">Chargement…</p>
    <p v-else-if="!routines.length && !showForm" class="routines__empty">
      Vous n’avez pas encore de routine. Créez-en une pour surveiller vos collections.
    </p>

    <ul class="routines__list">
      <li v-for="routine in routines" :key="routine.id" class="routine-card">
        <div class="routine-card__top">
          <h2 class="routine-card__name">{{ routine.name }}</h2>
          <span :class="`routine-card__state routine-card__state--${routine.state}`">
            {{ stateLabel(routine.state, routine.suspendedReason) }}
          </span>
        </div>
        <p class="routine-card__schedule">
          {{ describeSchedule(routine.schedule) }}
          <span v-if="routine.condition === 'only_if_new'"> · seulement s’il y a du nouveau</span>
        </p>
        <p class="routine-card__question">{{ routine.question }}</p>
        <dl class="routine-card__facts">
          <div>
            <dt>Prochaine exécution</dt>
            <dd>{{ routine.state === 'active' ? formatDateTime(routine.nextRunAt, routine.schedule.timezone) : '—' }}</dd>
          </div>
          <div>
            <dt>Dernier résultat</dt>
            <dd v-if="routine.lastRun">
              {{ runStatusLabel(routine.lastRun.status, routine.lastRun.skipReason) }}
              — {{ formatDateTime(routine.lastRun.startedAt) }}
              <router-link v-if="routine.lastRun.conversationId && routine.lastRun.status !== 'skipped'" :to="`/c/${routine.lastRun.conversationId}`">
                Ouvrir la conversation
              </router-link>
            </dd>
            <dd v-else>Aucune exécution</dd>
          </div>
        </dl>
        <p v-if="routine.state === 'suspended' && routine.suspendedReason !== 'admin'" class="routine-card__warning" role="status">
          Cette routine a été mise de côté. Reprenez-la quand vous voulez.
        </p>
        <div class="routine-card__actions">
          <button type="button" class="fr-btn fr-btn--sm" :disabled="busy === routine.id || !enabled" @click="run(routine)">
            Exécuter maintenant
          </button>
          <button
            type="button"
            class="fr-btn fr-btn--secondary fr-btn--sm"
            :disabled="busy === routine.id || (routine.state === 'suspended' && routine.suspendedReason === 'admin')"
            @click="toggle(routine)"
          >
            {{ routine.state === 'active' ? 'Mettre en pause' : 'Reprendre' }}
          </button>
          <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="startEdit(routine)">Modifier</button>
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm"
            :aria-expanded="openHistory === routine.id"
            @click="openHistory = openHistory === routine.id ? null : routine.id"
          >
            Historique
          </button>
          <button type="button" class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm routine-card__delete" @click="destroy(routine)">
            Supprimer
          </button>
        </div>
        <RoutineHistory v-if="openHistory === routine.id" :routine-id="routine.id" :refresh-key="historyKey" />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.routines {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.routines > * {
  max-width: 52rem;
  margin-left: auto;
  margin-right: auto;
}

.routines__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.routines__header h1 {
  margin: 0;
}

.routines__intro,
.routines__limits {
  margin-top: 0.5rem;
  margin-bottom: 1rem;
  color: var(--text-mention-grey);
}

.routines__limits {
  font-size: 0.875rem;
}

.routines__notice {
  margin-bottom: 1rem;
  padding: 0.625rem 0.875rem;
  border-radius: 0.5rem;
  background: var(--background-alt-blue-france);
  font-size: 0.875rem;
}

.routines__notice--off {
  background: var(--background-alt-grey);
}

.routines__notice--error {
  color: var(--text-default-error);
}

.routines__empty {
  margin-top: 3rem;
  text-align: center;
  color: var(--text-mention-grey);
}

.routines__list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-top: 1rem;
  margin-bottom: 0;
  padding: 0;
  list-style: none;
}

.routine-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.routine-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.routine-card__name {
  margin: 0;
  font-size: 1.0625rem;
}

.routine-card__state {
  padding: 0.125rem 0.5rem;
  border-radius: 999px;
  background: var(--background-alt-grey);
  font-size: 0.75rem;
  font-weight: 700;
}

.routine-card__state--active {
  background: var(--background-contrast-success);
  color: var(--text-default-success);
}

.routine-card__state--suspended {
  background: var(--background-contrast-warning);
}

.routine-card__schedule {
  margin: 0;
  font-weight: 600;
  font-size: 0.875rem;
}

.routine-card__question {
  margin: 0;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
  white-space: pre-wrap;
}

.routine-card__facts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 2rem;
  margin: 0;
  font-size: 0.8125rem;
}

.routine-card__facts dt {
  color: var(--text-mention-grey);
}

.routine-card__facts dd {
  margin: 0;
}

.routine-card__warning {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-default-warning);
}

.routine-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.routine-card__delete {
  margin-left: auto;
}
</style>
