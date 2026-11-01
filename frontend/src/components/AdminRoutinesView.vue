<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useAdminRoutines } from '../composables/useRoutines'
import type { RoutineSettings } from '../types/routine'
import { describeSchedule, formatDateTime, runStatusLabel, stateLabel } from '../utils/routines'

const { settings, routines, total, error, load, saveSettings, suspend, release } = useAdminRoutines()

const draft = reactive<RoutineSettings>({
  enabled: false,
  maxActivePerUser: 5,
  minIntervalMinutes: 60,
  maxRunsPerUserPerDay: 10,
  maxConcurrent: 3,
  maxConsecutiveFailures: 3,
  inactiveDays: 60,
  runTimeoutMinutes: 15,
})
const message = ref<string | null>(null)
const saved = ref(false)

onMounted(() => load())

watch(settings, (value) => value && Object.assign(draft, value), { immediate: true })

async function save() {
  message.value = await saveSettings(draft)
  saved.value = message.value === null
  if (saved.value) setTimeout(() => (saved.value = false), 2000)
}
</script>

<template>
  <section class="admin-view">
    <router-link to="/admin" class="admin-view__back">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
      </svg>
      Administration
    </router-link>
    <div class="admin-view__header">
      <h1>Routines</h1>
    </div>
    <p class="admin-view__intro">
      Facultatives et <strong>désactivées par défaut</strong> : une routine consomme des appels de modèle sans que personne
      ne soit devant l’écran, d’où les limites ci-dessous. Une routine agit avec les droits de son propriétaire au moment
      de l’exécution, jamais en administrateur, et sans les outils qui demandent son jeton.
    </p>

    <p v-if="error" class="admin-view__error" role="alert">{{ error }}</p>

    <form v-if="settings" class="admin-card" @submit.prevent="save">
      <div class="fr-toggle">
        <input id="routines-enabled" v-model="draft.enabled" type="checkbox" class="fr-toggle__input" />
        <label class="fr-toggle__label" for="routines-enabled" data-fr-checked-label="Activées" data-fr-unchecked-label="Désactivées">
          Fonction « Routines »
        </label>
      </div>
      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="routines-active">Routines actives par personne</label>
          <input id="routines-active" v-model.number="draft.maxActivePerUser" class="fr-input" type="number" min="1" max="100" />
        </div>
        <div class="admin-card__field">
          <label for="routines-interval">Intervalle minimal (minutes)</label>
          <input id="routines-interval" v-model.number="draft.minIntervalMinutes" class="fr-input" type="number" min="15" max="10080" />
        </div>
        <div class="admin-card__field">
          <label for="routines-day">Exécutions par personne et par jour</label>
          <input id="routines-day" v-model.number="draft.maxRunsPerUserPerDay" class="fr-input" type="number" min="1" max="1000" />
        </div>
      </div>
      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="routines-concurrent">Exécutions en même temps (toute l’application)</label>
          <input id="routines-concurrent" v-model.number="draft.maxConcurrent" class="fr-input" type="number" min="1" max="100" />
        </div>
        <div class="admin-card__field">
          <label for="routines-failures">Suspension après n échecs de suite</label>
          <input id="routines-failures" v-model.number="draft.maxConsecutiveFailures" class="fr-input" type="number" min="1" max="100" />
        </div>
        <div class="admin-card__field">
          <label for="routines-inactive">Suspension d’un compte inactif (jours)</label>
          <input id="routines-inactive" v-model.number="draft.inactiveDays" class="fr-input" type="number" min="1" max="3650" />
        </div>
        <div class="admin-card__field">
          <label for="routines-timeout">Durée maximale d’une exécution (minutes)</label>
          <input id="routines-timeout" v-model.number="draft.runTimeoutMinutes" class="fr-input" type="number" min="1" max="240" />
        </div>
      </div>
      <div class="admin-card__footer">
        <span v-if="saved" class="admin-card__saved" role="status">Enregistré</span>
        <span v-if="message" class="admin-card__error" role="alert">{{ message }}</span>
        <button type="submit" class="fr-btn">Enregistrer</button>
      </div>
    </form>

    <div v-if="settings" class="admin-card">
      <h2 class="admin-card__title">Toutes les routines ({{ total }})</h2>
      <p class="admin-card__intro">
        Qui, à quel rythme et pour quel coût sur 30 jours. Ni la question d’une routine ni ses réponses ne sont visibles ici.
      </p>
      <p v-if="!routines.length" class="admin-card__intro">Aucune routine.</p>
      <div v-else class="admin-table">
        <table>
          <caption class="fr-sr-only">Routines de l’application</caption>
          <thead>
            <tr>
              <th scope="col">Routine</th>
              <th scope="col">Propriétaire</th>
              <th scope="col">Rythme</th>
              <th scope="col">État</th>
              <th scope="col">Dernière exécution</th>
              <th scope="col">Jetons (30 j)</th>
              <th scope="col"><span class="fr-sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="routine in routines" :key="routine.id">
              <td>{{ routine.name }}</td>
              <td>{{ routine.ownerDisplay }}</td>
              <td>{{ describeSchedule(routine.schedule) }}</td>
              <td>{{ stateLabel(routine.state, routine.suspendedReason) }}</td>
              <td>
                {{ formatDateTime(routine.lastRunAt) }}
                <span v-if="routine.lastStatus" class="admin-table__muted">{{ runStatusLabel(routine.lastStatus) }}</span>
              </td>
              <td>{{ routine.tokens30Days.toLocaleString('fr-FR') }}</td>
              <td>
                <button
                  v-if="routine.state === 'suspended' && routine.suspendedReason === 'admin'"
                  type="button"
                  class="fr-btn fr-btn--secondary fr-btn--sm"
                  @click="release(routine.id)"
                >
                  Lever la suspension
                </button>
                <button v-else type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="suspend(routine.id)">
                  Suspendre
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.admin-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.admin-view__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  max-width: 56rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__header,
.admin-view__intro {
  max-width: 56rem;
  margin-left: auto;
  margin-right: auto;
}

.admin-view__header h1 {
  margin: 0;
}

.admin-view__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.admin-view__error {
  max-width: 56rem;
  margin: 1rem auto;
  color: var(--text-default-error);
}

.admin-card {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 56rem;
  margin: 0 auto 1.5rem;
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.admin-card__title {
  margin: 0;
  font-size: 1.0625rem;
}

.admin-card__intro {
  margin: 0;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.admin-card__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.admin-card__field {
  flex: 1;
  min-width: 11rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.admin-card__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.admin-card__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.admin-card__saved {
  margin-right: auto;
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.admin-card__error {
  margin-right: auto;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.admin-table {
  overflow-x: auto;
}

.admin-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.admin-table th,
.admin-table td {
  padding: 0.375rem 0.5rem;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border-default-grey);
}

.admin-table__muted {
  display: block;
  color: var(--text-mention-grey);
}
</style>
