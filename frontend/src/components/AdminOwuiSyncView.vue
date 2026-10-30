<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useOwuiSync } from '../composables/useOwuiSync'
import type { SyncedCollectionState } from '../types/owuiSync'
import { accountRows, runStatus } from '../utils/owuiSync'

const { latest, running, collections, isLoading, error, isStarting, refresh, start } = useOwuiSync()
onMounted(refresh)

const STATE_LABELS: Record<SyncedCollectionState, string> = {
  copied: 'Copiée',
  adopting: 'Reprise en cours',
  adopted: 'Reprise par Muffin',
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString('fr-FR') : '—'
}

const status = computed(() => (latest.value ? runStatus(latest.value) : null))
const rows = computed(() => accountRows(latest.value?.account ?? null))
</script>

<template>
  <section class="owui-sync">
    <router-link to="/admin" class="owui-sync__back">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
      </svg>
      Administration
    </router-link>
    <div class="owui-sync__header">
      <h1>Synchronisation avec Open WebUI</h1>
    </div>
    <p class="owui-sync__intro">
      Copie les groupes, les knowledge bases et les fichiers d'Open WebUI dans Muffin. Une collection copiée se lit et se cherche ici ;
      elle se modifie dans Open WebUI jusqu'à ce que Muffin la reprenne.
    </p>

    <p v-if="error" class="owui-sync__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="owui-sync__muted">Chargement…</p>

    <template v-else>
      <section class="owui-sync__card" aria-labelledby="owui-sync-latest">
        <div class="owui-sync__card-head">
          <h2 id="owui-sync-latest">Dernière synchronisation</h2>
          <button type="button" class="fr-btn fr-btn--sm" :disabled="running || isStarting" @click="start">
            {{ running || isStarting ? 'En cours…' : 'Synchroniser maintenant' }}
          </button>
        </div>

        <p v-if="!latest" class="owui-sync__muted">
          Aucune synchronisation n'a encore été lancée. Le worker de synchronisation doit pouvoir lire Open WebUI
          (<code>OWUI_BASE_URL</code> et <code>OWUI_API_KEY</code>) ; il la lance seul à intervalle régulier (beat ou CronJob) ou ici.
        </p>

        <template v-else>
          <p class="owui-sync__status">
            <span :class="['owui-sync__badge', `owui-sync__badge--${status?.tone}`]">{{ status?.label }}</span>
            Démarrée le {{ formatDate(latest.startedAt) }}<template v-if="latest.finishedAt">, terminée le {{ formatDate(latest.finishedAt) }}</template>
          </p>
          <p v-if="latest.error" class="owui-sync__error" role="alert">{{ latest.error }}</p>
          <p v-if="latest.stalled" class="owui-sync__error" role="alert">
            Cette synchronisation n'a jamais signalé sa fin : un worker s'est arrêté avec elle. Relancez-en une.
          </p>

          <table v-if="rows.length" class="owui-sync__table">
            <thead>
              <tr>
                <th scope="col"></th>
                <th scope="col">Vus</th>
                <th scope="col">En erreur</th>
                <th scope="col">Supprimés</th>
                <th scope="col">Non listés</th>
                <th scope="col">Vecteurs incohérents</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.label">
                <th scope="row">{{ row.label }}</th>
                <td>{{ row.counts.seen }}</td>
                <td :class="{ 'owui-sync__bad': row.counts.errors }">{{ row.counts.errors }}</td>
                <td>{{ row.counts.dropped }}</td>
                <td :class="{ 'owui-sync__bad': row.counts.unlisted }">{{ row.counts.unlisted ?? '—' }}</td>
                <td :class="{ 'owui-sync__bad': row.counts.inconsistent }">{{ row.counts.inconsistent ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </section>

      <section class="owui-sync__card" aria-labelledby="owui-sync-collections">
        <h2 id="owui-sync-collections">Collections copiées</h2>
        <p v-if="!collections.length" class="owui-sync__muted">Aucune collection n'a été copiée d'Open WebUI.</p>
        <table v-else class="owui-sync__table">
          <thead>
            <tr>
              <th scope="col">Collection</th>
              <th scope="col">État</th>
              <th scope="col">Documents</th>
              <th scope="col">Résumés</th>
              <th scope="col">Dernière synchronisation</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="collection in collections" :key="collection.id">
              <th scope="row">
                <router-link :to="`/collections/${collection.id}`">{{ collection.name }}</router-link>
                <span class="owui-sync__muted owui-sync__id">{{ collection.externalId }}</span>
                <ul v-if="collection.problems.length" class="owui-sync__problems">
                  <li v-for="problem in collection.problems" :key="problem">{{ problem }}</li>
                </ul>
              </th>
              <td>
                <span :class="['owui-sync__badge', `owui-sync__badge--${collection.state === 'adopted' ? 'success' : collection.state === 'adopting' ? 'info' : 'neutral'}`]">
                  {{ STATE_LABELS[collection.state] }}
                </span>
              </td>
              <td>{{ collection.documentCount }}</td>
              <td>{{ collection.summaryCount }}</td>
              <td>{{ collection.state === 'adopted' ? '—' : formatDate(collection.syncedAt) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.owui-sync {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.owui-sync > * {
  max-width: 56rem;
  margin-left: auto;
  margin-right: auto;
}

.owui-sync__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.owui-sync__header h1 {
  margin: 0;
}

.owui-sync__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.owui-sync__card {
  margin-bottom: 1.5rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.owui-sync__card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.owui-sync__card h2 {
  margin: 0 0 0.75rem;
  font-size: 1.125rem;
}

.owui-sync__card-head h2 {
  margin: 0;
}

.owui-sync__muted {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.owui-sync__id {
  display: block;
  font-weight: 400;
  font-size: 0.75rem;
}

.owui-sync__status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.owui-sync__badge {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.75rem;
  font-weight: 700;
  background: var(--background-contrast-grey);
}

.owui-sync__badge--success {
  background: var(--background-contrast-success);
  color: var(--text-default-success);
}

.owui-sync__badge--info {
  background: var(--background-contrast-info);
  color: var(--text-default-info);
}

.owui-sync__badge--warning {
  background: var(--background-contrast-warning);
  color: var(--text-default-warning);
}

.owui-sync__badge--error {
  background: var(--background-contrast-error);
  color: var(--text-default-error);
}

.owui-sync__error {
  color: var(--text-default-error);
}

.owui-sync__table {
  width: 100%;
  margin-top: 1rem;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.owui-sync__table th,
.owui-sync__table td {
  padding: 0.5rem 0.75rem;
  text-align: left;
  border-bottom: 1px solid var(--border-default-grey);
  vertical-align: top;
}

.owui-sync__bad {
  color: var(--text-default-error);
  font-weight: 700;
}

.owui-sync__problems {
  margin: 0.25rem 0 0;
  padding-left: 1rem;
  font-weight: 400;
  font-size: 0.75rem;
  color: var(--text-default-warning);
}
</style>
