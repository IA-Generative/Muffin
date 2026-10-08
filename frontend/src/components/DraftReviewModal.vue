<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  useDocumentDraft,
  type DocumentDraft,
  type DraftImage,
  type DraftPreview,
} from '../composables/useDocumentDraft'

const props = defineProps<{
  collectionId: string
  documentId: string
  draft: DocumentDraft
  // An action (validate, adjust, upload...) is in flight: every button waits.
  busy: boolean
  error: string | null
}>()

const emit = defineEmits<{
  close: []
  adjust: [prompt: string]
  validate: []
  refuse: []
  upload: [imageId: string, file: File]
  insertImages: []
}>()

const { fetchPreview, releasePreview } = useDocumentDraft()

const preview = ref<DraftPreview | null>(null)
const previewError = ref(false)
const adjustPrompt = ref('')

const isPending = computed(() => props.draft.status === 'pending')
const canValidate = computed(
  () => props.draft.status === 'ready' && props.draft.edited && !props.busy,
)
// One line per operation the agent applied (the backend sends them as "- ..." lines), or - when it
// changed nothing - its own explanation.
const summaryLines = computed(() =>
  props.draft.operationsSummary
    .split('\n')
    .map((line) => line.replace(/^-\s*/, '').trim())
    .filter(Boolean),
)
const uploadedCount = computed(() => props.draft.pendingImages.filter((image) => image.uploaded).length)
const markdownHtml = computed(() =>
  preview.value?.kind === 'markdown' ? DOMPurify.sanitize(marked.parse(preview.value.text, { async: false })) : '',
)

// Reload the preview whenever the draft it belongs to changes - a new job finished (an adjustment, or
// images were inserted) - rather than on every poll.
const previewKey = computed(() => {
  const { id, status, jobKind, operationsSummary, edited } = props.draft
  return status === 'ready' && edited && props.draft.preview
    ? `${id}|${jobKind}|${operationsSummary}`
    : null
})

async function loadPreview() {
  releasePreview(preview.value)
  preview.value = null
  previewError.value = false
  if (!previewKey.value || !props.draft.preview) return
  try {
    preview.value = await fetchPreview(props.collectionId, props.documentId, props.draft.preview)
  } catch {
    previewError.value = true
  }
}

watch(previewKey, loadPreview, { immediate: true })
onUnmounted(() => releasePreview(preview.value))

function where(image: DraftImage): string {
  const section = image.section?.heading
  if (!image.section) return 'à la fin du document'
  const position = image.afterParagraph === null ? 'à la fin' : `après le paragraphe ${image.afterParagraph}`
  return `${position} de « ${section ?? 'début du document'} »`
}

function onFile(image: DraftImage, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // lets the same file be picked again after a refusal
  if (file) emit('upload', image.id, file)
}

function submitAdjust() {
  const prompt = adjustPrompt.value.trim()
  if (!prompt || props.busy || isPending.value) return
  emit('adjust', prompt)
  adjustPrompt.value = ''
}
</script>

<template>
  <div class="review-overlay" @click.self="emit('close')">
    <div class="review" role="dialog" aria-modal="true" aria-labelledby="review-title">
      <header class="review__header">
        <h2 id="review-title" class="review__title">Modification proposée</h2>
        <button type="button" class="review__close" aria-label="Fermer (la proposition est conservée)" @click="emit('close')">
          ✕
        </button>
      </header>
      <p class="review__prompt"><strong>Votre demande :</strong> {{ draft.prompt }}</p>

      <div class="review__content">
        <section class="review__preview" aria-label="Aperçu du document modifié">
          <p v-if="isPending" class="review__state" role="status">
            <span class="review__spinner" aria-hidden="true" />
            {{ draft.jobKind === 'images' ? 'Insertion des images…' : 'L’agent prépare la modification…' }}
          </p>
          <p v-else-if="draft.status === 'failed'" class="review__state review__state--error" role="alert">
            {{ draft.error ?? 'La modification a échoué.' }}
          </p>
          <p v-else-if="!draft.edited" class="review__state">Aucune modification à prévisualiser.</p>
          <p v-else-if="previewError" class="review__state review__state--error" role="alert">
            Impossible de charger l’aperçu.
          </p>
          <p v-else-if="!preview" class="review__state" role="status">Chargement de l’aperçu…</p>
          <iframe
            v-else-if="preview.kind === 'pdf'"
            :src="preview.url"
            class="review__pdf"
            title="Aperçu PDF du document modifié"
          />
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div v-else class="review__markdown" v-html="markdownHtml" />
        </section>

        <aside class="review__side">
          <section v-if="draft.status === 'ready'">
            <h3 class="review__section-title">{{ draft.edited ? 'Ce qui a changé' : 'Réponse de l’agent' }}</h3>
            <ul v-if="draft.edited && summaryLines.length" class="review__summary">
              <li v-for="line in summaryLines" :key="line">{{ line }}</li>
            </ul>
            <p v-else-if="!draft.edited" class="review__explanation">
              {{ draft.operationsSummary || 'L’agent n’a rien modifié.' }}
            </p>
          </section>

          <section v-if="draft.pendingImages.length">
            <h3 class="review__section-title">Images</h3>
            <p v-if="draft.format !== 'odt'" class="review__hint">
              Les images ne sont pas prises en charge dans un document Markdown.
            </p>
            <template v-else>
              <p class="review__hint">
                L’agent ne crée pas d’image : déposez le fichier (PNG, JPEG ou GIF, 10 Mo au plus) pour les
                emplacements qui vous intéressent.
              </p>
              <ul class="review__images">
                <li v-for="image in draft.pendingImages" :key="image.id" class="review__image">
                  <span class="review__image-name">{{ image.description }}</span>
                  <span class="review__hint">{{ where(image) }}</span>
                  <span v-if="image.inserted" class="review__badge review__badge--done">Insérée</span>
                  <label v-else class="fr-btn fr-btn--tertiary fr-btn--sm review__file" :class="{ 'review__file--disabled': busy || isPending }">
                    {{ image.uploaded ? 'Changer le fichier' : 'Déposer un fichier' }}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/gif"
                      class="review__file-input"
                      :disabled="busy || isPending"
                      :aria-label="`Choisir l’image pour : ${image.description}`"
                      @change="onFile(image, $event)"
                    />
                  </label>
                  <span v-if="image.uploaded" class="review__badge">Déposée</span>
                </li>
              </ul>
              <button
                v-if="draft.pendingImages.some((image) => !image.inserted)"
                type="button"
                class="fr-btn fr-btn--secondary fr-btn--sm"
                :disabled="uploadedCount === 0 || busy || isPending"
                @click="emit('insertImages')"
              >
                Insérer {{ uploadedCount > 1 ? `les ${uploadedCount} images déposées` : 'l’image déposée' }}
              </button>
            </template>
          </section>

          <section>
            <h3 class="review__section-title">Ajuster</h3>
            <label class="review__hint" for="review-adjust">
              Une consigne de plus, appliquée à cette proposition.
            </label>
            <textarea
              id="review-adjust"
              v-model="adjustPrompt"
              class="review__textarea"
              rows="3"
              maxlength="4000"
              placeholder="Par exemple : plus court, ou ajoute aussi…"
              :disabled="busy || isPending"
            />
            <button
              type="button"
              class="fr-btn fr-btn--secondary fr-btn--sm"
              :disabled="!adjustPrompt.trim() || busy || isPending"
              @click="submitAdjust"
            >
              Ajuster
            </button>
          </section>

          <p v-if="error" class="review__error" role="alert">{{ error }}</p>
          <p v-else-if="draft.error && draft.status === 'ready'" class="review__error" role="alert">
            {{ draft.error }}
          </p>
        </aside>
      </div>

      <footer class="review__footer">
        <p class="review__hint">
          La proposition est conservée tant que la fiche du document reste ouverte ; rien n’est écrit dans la
          collection avant votre validation.
        </p>
        <div class="review__actions">
          <button type="button" class="fr-btn fr-btn--secondary" :disabled="busy" @click="emit('refuse')">Refuser</button>
          <button type="button" class="fr-btn" :disabled="!canValidate" @click="emit('validate')">
            Valider la modification
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.review-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 110;
  padding: 1rem;
}

.review {
  width: 100%;
  max-width: 78rem;
  height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.review__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem 0;
}

.review__title {
  margin: 0;
  font-size: 1.125rem;
}

.review__close {
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.review__prompt {
  margin: 0.5rem 1.5rem 0;
  font-size: 0.875rem;
}

.review__content {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 1.25rem;
  padding: 1rem 1.5rem;
}

.review__preview {
  flex: 3;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  overflow: auto;
  background: var(--background-alt-grey);
}

.review__pdf {
  flex: 1;
  width: 100%;
  border: none;
}

.review__markdown {
  padding: 1.25rem 1.5rem;
  background: var(--background-default-grey);
  min-height: 100%;
}

.review__state {
  margin: auto;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  color: var(--text-mention-grey);
  font-size: 0.9375rem;
  padding: 1.5rem;
  text-align: center;
}

.review__state--error,
.review__error {
  color: var(--text-default-error);
}

.review__spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid var(--border-default-grey);
  border-top-color: var(--border-action-high-blue-france);
  border-radius: 50%;
  animation: review-spin 0.8s linear infinite;
}

@keyframes review-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .review__spinner {
    animation: none;
  }
}

.review__side {
  flex: 2;
  min-width: 17rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.review__section-title {
  margin: 0 0 0.5rem;
  font-size: 0.9375rem;
}

.review__summary,
.review__images {
  margin: 0 0 0.75rem;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.review__summary li {
  padding: 0.5rem 0.75rem;
  border-left: 3px solid var(--border-plain-success);
  background: var(--background-alt-grey);
  font-size: 0.875rem;
}

.review__explanation {
  margin: 0;
  font-size: 0.875rem;
}

.review__image {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.625rem;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.review__image-name {
  flex-basis: 100%;
  font-size: 0.875rem;
  font-weight: 600;
}

.review__hint {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.review__image .review__hint {
  flex-basis: 100%;
  margin: 0;
}

.review__badge {
  padding: 0 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-contrast-info);
  color: var(--text-default-info);
  font-size: 0.75rem;
}

.review__badge--done {
  background: var(--background-contrast-success);
  color: var(--text-default-success);
}

.review__file {
  position: relative;
  cursor: pointer;
}

.review__file--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.review__file-input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: inherit;
}

.review__textarea {
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  resize: vertical;
}

.review__error {
  margin: 0;
  font-size: 0.875rem;
}

.review__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.875rem 1.5rem 1.25rem;
  border-top: 1px solid var(--border-default-grey);
}

.review__footer .review__hint {
  margin: 0;
}

.review__actions {
  flex-shrink: 0;
  display: flex;
  gap: 0.5rem;
}

@media (max-width: 62rem) {
  .review__content {
    flex-direction: column;
    overflow-y: auto;
  }

  .review__preview {
    flex: none;
    min-height: 22rem;
  }

  .review__side {
    flex: none;
    overflow: visible;
  }
}
</style>
