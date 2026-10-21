<script setup lang="ts">
import { computed, ref } from 'vue'
import { useUsage } from '../composables/useUsage'
import UsageCharts from './usage/UsageCharts.vue'
import UsagePeriodSelector from './usage/UsagePeriodSelector.vue'

const days = ref(30)
const userId = ref<string | null>(null)
const userIdDraft = ref('')
// One request: the per-user list always covers everyone, even when narrowed to one user_id.
const { usage, isLoading, error } = useUsage(days, { admin: true, userId })

const selectedLabel = computed(() => {
  if (!userId.value) return null
  const row = usage.value?.byUser.find((item) => item.userId === userId.value)
  return row?.display ?? userId.value
})

function selectUser(id: string | null) {
  userId.value = id
  userIdDraft.value = id ?? ''
}

function submitUserId() {
  selectUser(userIdDraft.value.trim() || null)
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
      <h1>Consommation</h1>
      <UsagePeriodSelector v-model="days" />
    </div>
    <p class="admin-view__intro">
      Tous les appels aux modèles (chat, traitement des documents, évaluation), pour tout le monde ou pour un
      utilisateur.
    </p>

    <div class="admin-view__content">
      <form class="admin-usage__filter" @submit.prevent="submitUserId">
        <label for="usage-user-id">Filtrer par user_id</label>
        <div class="admin-usage__filter-row">
          <input id="usage-user-id" v-model="userIdDraft" type="text" placeholder="Identifiant Keycloak (sub)" />
          <button type="submit" class="fr-btn fr-btn--sm">Filtrer</button>
          <button v-if="userId" type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="selectUser(null)">
            Tout le monde
          </button>
        </div>
        <p class="admin-usage__current">
          {{ selectedLabel ? `Consommation de ${selectedLabel}` : 'Consommation de tout le monde' }}
        </p>
      </form>

      <p v-if="error" class="admin-usage__error" role="alert">{{ error }}</p>
      <p v-else-if="isLoading && !usage" class="admin-usage__empty">Chargement…</p>
      <p v-else-if="usage && usage.byUser.length === 0" class="admin-usage__empty">
        Aucune consommation sur les {{ days }} derniers jours.
      </p>
      <UsageCharts v-else-if="usage" :usage="usage" :selected-user="userId" @select-user="selectUser" />
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
  max-width: 64rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__back:hover {
  color: var(--text-default-grey);
}

.admin-view__header,
.admin-view__intro,
.admin-view__content {
  max-width: 64rem;
  margin: 0 auto;
}

.admin-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.admin-view__header h1 {
  margin: 0;
}

.admin-view__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.admin-usage__filter {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-bottom: 1.25rem;
}

.admin-usage__filter label {
  font-size: 0.8125rem;
  font-weight: 700;
}

.admin-usage__filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.admin-usage__filter-row input {
  flex: 1;
  min-width: 12rem;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.admin-usage__current {
  margin: 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.admin-usage__empty,
.admin-usage__error {
  margin: 3rem 0;
  text-align: center;
  color: var(--text-mention-grey);
}

.admin-usage__error {
  color: var(--text-default-error);
}
</style>
