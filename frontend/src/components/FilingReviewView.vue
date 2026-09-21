<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useFiling, type FilingCandidate } from '../composables/useFiling'
import FileFilingModal from './FileFilingModal.vue'

const { candidates, isLoading, error, fetchFilingCandidates, decideFiling, uploadStandaloneFile } = useFiling()
onMounted(fetchFilingCandidates)

const modalCandidate = ref<FilingCandidate>()
const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)
const uploadError = ref<string | null>(null)

function openFilePicker() {
  fileInput.value?.click()
}

async function handleFilesSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const files = target.files
  target.value = ''
  if (!files?.length) return
  uploading.value = true
  uploadError.value = null
  try {
    for (const file of files) await uploadStandaloneFile(file)
  } catch {
    uploadError.value = "Échec de l'envoi d'un ou plusieurs fichiers."
  } finally {
    uploading.value = false
  }
}

async function decide(action: 'accept' | 'choose_other' | 'dismiss', targetCollectionId?: string) {
  const candidate = modalCandidate.value
  if (!candidate) return
  try {
    await decideFiling(candidate.id, action, targetCollectionId)
  } finally {
    modalCandidate.value = undefined
  }
}

function scorePercent(score: number | null): string | null {
  return score === null ? null : `${Math.round(score * 100)}%`
}
</script>

<template>
  <section class="filing-view">
    <div class="filing-view__header">
      <h1>Fichiers à ranger</h1>
      <div class="filing-view__header-actions">
        <input
          ref="fileInput"
          type="file"
          multiple
          class="filing-view__file-input"
          aria-label="Choisir des fichiers à envoyer"
          @change="handleFilesSelected"
        />
        <button type="button" class="fr-btn fr-btn--secondary" :disabled="uploading" @click="openFilePicker">
          {{ uploading ? 'Envoi…' : 'Uploader un fichier' }}
        </button>
        <button type="button" class="fr-btn fr-btn--secondary" @click="fetchFilingCandidates">Actualiser</button>
      </div>
    </div>
    <p class="filing-view__intro">
      Fichiers que vous avez uploadés directement dans une conversation (ou ici même) et qui ne sont pas (ou plus)
      dans une collection permanente que vous gérez.
    </p>

    <p v-if="uploadError" class="filing-view__error" role="alert">{{ uploadError }}</p>
    <p v-if="error" class="filing-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading" class="filing-view__empty">Chargement…</p>
    <p v-else-if="candidates.length === 0" class="filing-view__empty">Aucun fichier à ranger pour le moment.</p>

    <table v-else class="filing-view__table">
      <thead>
        <tr>
          <th scope="col">Fichier</th>
          <th scope="col">Collection actuelle</th>
          <th scope="col">Suggestion</th>
          <th scope="col">Statut</th>
          <th scope="col"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="candidate in candidates" :key="candidate.id">
          <td>{{ candidate.name }}</td>
          <td>
            {{ candidate.collectionName }}
            <span v-if="candidate.collectionIsTemporary" class="filing-view__tag">temporaire</span>
            <span v-else-if="!candidate.collectionEditable" class="filing-view__tag filing-view__tag--warning">
              non modifiable
            </span>
          </td>
          <td>
            <template v-if="candidate.suggestedCollectionName">
              {{ candidate.suggestedCollectionName }}
              <span v-if="candidate.suggestedCollectionScore !== null" class="filing-view__score">
                {{ scorePercent(candidate.suggestedCollectionScore) }}
              </span>
            </template>
            <span v-else class="filing-view__empty-cell">—</span>
          </td>
          <td>
            <span v-if="candidate.filingDismissed" class="filing-view__tag">ignoré</span>
          </td>
          <td>
            <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="modalCandidate = candidate">
              Ranger
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <FileFilingModal
      v-if="modalCandidate"
      :file="modalCandidate"
      @close="modalCandidate = undefined"
      @decide="decide"
    />
  </section>
</template>

<style scoped>
.filing-view {
  flex: 1;
  padding: 1.5rem 2rem;
  overflow-y: auto;
}

.filing-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
}

.filing-view__header-actions {
  display: flex;
  gap: 0.5rem;
}

.filing-view__file-input {
  display: none;
}

.filing-view__intro {
  color: var(--text-mention-grey);
  margin-bottom: 1.5rem;
}

.filing-view__error {
  color: var(--text-default-error);
}

.filing-view__empty {
  color: var(--text-mention-grey);
}

.filing-view__table {
  width: 100%;
  border-collapse: collapse;
}

.filing-view__table th,
.filing-view__table td {
  text-align: left;
  padding: 0.625rem 0.75rem;
  border-bottom: 1px solid var(--border-default-grey);
  font-size: 0.875rem;
}

.filing-view__tag {
  display: inline-block;
  margin-left: 0.375rem;
  padding: 0.0625rem 0.5rem;
  border-radius: 999px;
  background: var(--background-alt-grey-hover);
  color: var(--text-mention-grey);
  font-size: 0.6875rem;
}

.filing-view__tag--warning {
  background: var(--background-contrast-error);
  color: var(--text-default-error);
}

.filing-view__score {
  color: var(--text-mention-grey);
  font-size: 0.75rem;
}

.filing-view__empty-cell {
  color: var(--text-disabled-grey);
}
</style>
