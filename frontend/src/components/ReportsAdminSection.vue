<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { ReportStatus, ReportType } from '../composables/useReports'
import { useReportsAdmin } from '../composables/useReportsAdmin'

const { reports, isLoading, error, fetchReports, updateReport } = useReportsAdmin()

const statusFilter = ref<ReportStatus | ''>('')
const typeFilter = ref<ReportType | ''>('')
onMounted(() => fetchReports())
watch([statusFilter, typeFilter], () =>
  fetchReports(statusFilter.value || undefined, typeFilter.value || undefined),
)

const expandedId = ref<string | null>(null)
const responseDraft = ref('')
const statusDraft = ref<ReportStatus>('new')

function expand(id: string, currentStatus: ReportStatus) {
  expandedId.value = expandedId.value === id ? null : id
  statusDraft.value = currentStatus
  responseDraft.value = ''
}

async function submitUpdate(id: string) {
  await updateReport(id, statusDraft.value, responseDraft.value.trim() || undefined)
  expandedId.value = null
}

const TYPE_LABELS: Record<ReportType, string> = { bug: 'Bug', idea: 'Idée', question: 'Question' }
const STATUS_LABELS: Record<ReportStatus, string> = {
  new: 'Nouveau',
  in_progress: 'En cours',
  resolved: 'Résolu',
  wont_fix: 'Refusé',
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <div class="reports-admin">
    <div class="reports-admin__filters">
      <select v-model="statusFilter" class="fr-select" aria-label="Filtrer par statut">
        <option value="">Tous les statuts</option>
        <option value="new">Nouveau</option>
        <option value="in_progress">En cours</option>
        <option value="resolved">Résolu</option>
        <option value="wont_fix">Refusé</option>
      </select>
      <select v-model="typeFilter" class="fr-select" aria-label="Filtrer par type">
        <option value="">Tous les types</option>
        <option value="bug">Bug</option>
        <option value="idea">Idée</option>
        <option value="question">Question</option>
      </select>
    </div>

    <p v-if="isLoading" class="reports-admin__empty">Chargement…</p>
    <p v-else-if="error" class="reports-admin__error">{{ error }}</p>
    <p v-else-if="reports.length === 0" class="reports-admin__empty">Aucun signalement.</p>

    <ul v-else class="reports-admin__list">
      <li v-for="report in reports" :key="report.id" class="reports-admin__item">
        <button
          type="button"
          class="reports-admin__item-header"
          :aria-expanded="expandedId === report.id"
          @click="expand(report.id, report.status)"
        >
          <span class="reports-admin__item-title">{{ report.title }}</span>
          <span class="reports-admin__item-badge" :class="`reports-admin__item-badge--${report.status}`">
            {{ STATUS_LABELS[report.status] }}
          </span>
        </button>
        <p class="reports-admin__item-meta">
          {{ TYPE_LABELS[report.type] }} · {{ report.userDisplay }} · {{ formatDate(report.createdAt) }}
        </p>

        <div v-if="expandedId === report.id" class="reports-admin__item-detail">
          <p class="reports-admin__item-description">{{ report.description }}</p>
          <img
            v-if="report.screenshotUrl"
            :src="report.screenshotUrl"
            alt="Capture d'écran jointe au signalement"
            class="reports-admin__item-screenshot"
          />

          <label :for="`status-${report.id}`">Statut</label>
          <select :id="`status-${report.id}`" v-model="statusDraft" class="fr-select">
            <option value="new">Nouveau</option>
            <option value="in_progress">En cours</option>
            <option value="resolved">Résolu</option>
            <option value="wont_fix">Refusé</option>
          </select>

          <label :for="`response-${report.id}`">Réponse (optionnel)</label>
          <textarea
            :id="`response-${report.id}`"
            v-model="responseDraft"
            rows="3"
            :placeholder="report.adminResponse ?? 'Répondre à ce signalement…'"
          />

          <button type="button" class="fr-btn fr-btn--sm" @click="submitUpdate(report.id)">Enregistrer</button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.reports-admin__filters {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.reports-admin__empty,
.reports-admin__error {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.reports-admin__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.reports-admin__item {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
}

.reports-admin__item-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 0;
  font: inherit;
  color: var(--text-default-grey);
  text-align: left;
}

.reports-admin__item-title {
  font-weight: 700;
}

.reports-admin__item-badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.reports-admin__item-badge--resolved {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.reports-admin__item-badge--in_progress {
  background: var(--background-alt-orange-terre-battue, var(--background-alt-grey));
  color: var(--text-default-grey);
}

.reports-admin__item-meta {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.reports-admin__item-detail {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-default-grey);
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.reports-admin__item-description {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  white-space: pre-wrap;
}

.reports-admin__item-screenshot {
  max-width: 100%;
  max-height: 16rem;
  border-radius: 0.375rem;
  margin-bottom: 0.5rem;
}

.reports-admin__item-detail label {
  font-size: 0.8125rem;
  font-weight: 700;
}

.reports-admin__item-detail select,
.reports-admin__item-detail textarea {
  width: 100%;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  box-sizing: border-box;
  resize: vertical;
}

.reports-admin__item-detail button {
  align-self: flex-start;
  margin-top: 0.25rem;
}
</style>
