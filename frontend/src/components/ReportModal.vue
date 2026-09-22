<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useReports } from '../composables/useReports'
import type { ReportStatus, ReportType } from '../composables/useReports'

const emit = defineEmits<{ close: [] }>()

const { myReports, error, fetchMyReports, createReport } = useReports()

const type = ref<ReportType>('bug')
const title = ref('')
const description = ref('')
const screenshot = ref<Blob | null>(null)
const screenshotPreviewUrl = ref<string | null>(null)
const isSubmitting = ref(false)
const submitted = ref(false)

onMounted(fetchMyReports)

function setScreenshot(blob: Blob | null) {
  if (screenshotPreviewUrl.value) URL.revokeObjectURL(screenshotPreviewUrl.value)
  screenshot.value = blob
  screenshotPreviewUrl.value = blob ? URL.createObjectURL(blob) : null
}

function onFileChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) setScreenshot(file)
}

// A screenshot taken with the OS's own tool (capture d'écran system) lands on the clipboard -
// pasting it here is the lightest way to "take a screenshot" without a DOM-capture library and
// its edge cases (canvas/video/iframe content that renders wrong) - see §148.
function onPaste(event: ClipboardEvent) {
  const item = Array.from(event.clipboardData?.items ?? []).find((entry) => entry.type.startsWith('image/'))
  const file = item?.getAsFile()
  if (file) setScreenshot(file)
}

const canSubmit = computed(() => title.value.trim() !== '' && description.value.trim() !== '' && !isSubmitting.value)

async function submit() {
  if (!canSubmit.value) return
  isSubmitting.value = true
  const ok = await createReport(type.value, title.value.trim(), description.value.trim(), screenshot.value)
  isSubmitting.value = false
  if (ok) {
    title.value = ''
    description.value = ''
    setScreenshot(null)
    submitted.value = true
  }
}

const TYPE_LABELS: Record<ReportType, string> = { bug: 'Bug', idea: 'Idée', question: 'Question' }
const STATUS_LABELS: Record<ReportStatus, string> = {
  new: 'Nouveau',
  in_progress: 'En cours',
  resolved: 'Résolu',
  wont_fix: 'Refusé',
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <div class="report-overlay" @click.self="emit('close')">
    <div class="report-modal" role="dialog" aria-modal="true" aria-labelledby="report-modal-title">
      <button type="button" class="report-modal__close" aria-label="Fermer" @click="emit('close')">✕</button>
      <h2 id="report-modal-title">Signaler un bug ou une idée</h2>

      <form class="report-modal__form" @submit.prevent="submit">
        <label for="report-type">Type</label>
        <select id="report-type" v-model="type" class="fr-select">
          <option value="bug">Bug</option>
          <option value="idea">Idée</option>
          <option value="question">Question</option>
        </select>

        <label for="report-title">Titre</label>
        <input id="report-title" v-model="title" type="text" placeholder="En une phrase…" required />

        <label for="report-description">Description</label>
        <textarea
          id="report-description"
          v-model="description"
          rows="4"
          placeholder="Décrivez ce que vous avez observé, ou votre idée…"
          @paste="onPaste"
        />

        <label>Capture d'écran (optionnel)</label>
        <div class="report-modal__screenshot">
          <img v-if="screenshotPreviewUrl" :src="screenshotPreviewUrl" alt="Aperçu de la capture d'écran jointe" />
          <p v-else class="report-modal__screenshot-hint">
            Collez une capture (Ctrl+V) après une capture d'écran système, ou choisissez un fichier.
          </p>
          <div class="report-modal__screenshot-actions">
            <input type="file" accept="image/*" aria-label="Choisir une capture d'écran" @change="onFileChange" />
            <button v-if="screenshot" type="button" class="fr-btn fr-btn--tertiary" @click="setScreenshot(null)">
              Retirer
            </button>
          </div>
        </div>

        <p v-if="error" class="report-modal__error">{{ error }}</p>
        <p v-if="submitted" class="report-modal__success">Signalement envoyé, merci !</p>

        <button type="submit" class="fr-btn" :disabled="!canSubmit">Envoyer</button>
      </form>

      <section class="report-modal__history">
        <h3>Mes signalements</h3>
        <p v-if="myReports.length === 0" class="report-modal__history-empty">Aucun signalement pour le moment.</p>
        <ul v-else class="report-modal__history-list">
          <li v-for="report in myReports" :key="report.id" class="report-modal__history-item">
            <div class="report-modal__history-row">
              <span class="report-modal__history-title">{{ report.title }}</span>
              <span class="report-modal__history-badge" :class="`report-modal__history-badge--${report.status}`">
                {{ STATUS_LABELS[report.status] }}
              </span>
            </div>
            <p class="report-modal__history-meta">
              {{ TYPE_LABELS[report.type] }} · {{ formatDate(report.createdAt) }}
            </p>
            <p v-if="report.adminResponse" class="report-modal__history-response">
              <strong>Réponse :</strong> {{ report.adminResponse }}
            </p>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.report-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 1.5rem;
}

.report-modal {
  position: relative;
  width: 100%;
  max-width: 30rem;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.75rem;
  box-sizing: border-box;
  padding: 1.75rem;
}

.report-modal__close {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.report-modal h2 {
  margin: 0 0 1rem;
  font-size: 1.1875rem;
}

.report-modal__form {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.report-modal__form label {
  font-size: 0.8125rem;
  font-weight: 700;
  margin-top: 0.5rem;
}

.report-modal__form input[type='text'],
.report-modal__form textarea,
.report-modal__form select {
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

.report-modal__screenshot {
  border: 1px dashed var(--border-default-grey);
  border-radius: 0.5rem;
  padding: 0.75rem;
}

.report-modal__screenshot img {
  max-width: 100%;
  max-height: 10rem;
  display: block;
  margin-bottom: 0.5rem;
  border-radius: 0.375rem;
}

.report-modal__screenshot-hint {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.report-modal__screenshot-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.report-modal__error {
  color: var(--text-default-error);
  font-size: 0.8125rem;
  margin: 0.25rem 0 0;
}

.report-modal__success {
  color: var(--text-default-success, #18753c);
  font-size: 0.8125rem;
  margin: 0.25rem 0 0;
}

.report-modal__form button[type='submit'] {
  margin-top: 0.75rem;
  align-self: flex-start;
}

.report-modal__history {
  margin-top: 1.75rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--border-default-grey);
}

.report-modal__history h3 {
  margin: 0 0 0.75rem;
  font-size: 0.9375rem;
}

.report-modal__history-empty {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.report-modal__history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.report-modal__history-item {
  padding: 0.625rem 0.75rem;
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
}

.report-modal__history-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.report-modal__history-title {
  font-size: 0.875rem;
  font-weight: 700;
}

.report-modal__history-badge {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--background-alt-grey-hover);
  color: var(--text-mention-grey);
}

.report-modal__history-badge--resolved {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.report-modal__history-badge--in_progress {
  background: var(--background-alt-orange-terre-battue, var(--background-alt-grey));
  color: var(--text-default-grey);
}

.report-modal__history-meta {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.report-modal__history-response {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
}
</style>
