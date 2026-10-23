<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { highlightPassage, type PassageMatch } from '../utils/highlightPassage'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// A passage that goes on over a page break is followed onto the next pages, up to this many more.
const MAX_FOLLOWING_PAGES = 4

const props = defineProps<{
  collectionId: string
  documentId: string
  documentName: string
  pageNumber?: number
  // The exact chunk text that was actually retrieved and cited, or the evidence of a question-answer
  // pair - already in hand from the citation itself, never refetched.
  excerpt?: string
}>()

const emit = defineEmits<{
  close: []
}>()

interface DocumentPage {
  page_number: number
  content: string
  screenshot_url: string | null
}

interface CitedPage {
  page: DocumentPage
  match: PassageMatch
}

// The pages the passage is on - the cited one, and the next ones when it goes on over the page break.
const cited = ref<CitedPage[]>([])
const index = ref(0)
const pageError = ref(false)
const loading = ref(true)

const current = computed(() => cited.value[index.value])

async function fetchPage(number: number): Promise<DocumentPage | undefined> {
  const response = await fetch(
    `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/pages` +
      `?page=${number}&page_size=1`,
    { credentials: 'include' },
  )
  if (!response.ok) throw new Error(`${response.status}`)
  const body: { items: DocumentPage[] } = await response.json()
  return body.items[0]
}

onMounted(async () => {
  if (!props.pageNumber) {
    loading.value = false
    return
  }
  try {
    const first = await fetchPage(props.pageNumber)
    if (first) {
      let match = highlightPassage(first.content, props.excerpt)
      cited.value = [{ page: first, match }]
      // The last fragment of the passage is not on this page: it goes on over the page break.
      for (let step = 1; step <= MAX_FOLLOWING_PAGES && match.matched && !match.lastFound; step++) {
        const next = await fetchPage(props.pageNumber + step)
        if (!next) break
        match = highlightPassage(next.content, props.excerpt)
        if (!match.matched) break
        cited.value = [...cited.value, { page: next, match }]
      }
    }
  } catch {
    pageError.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="source-document-modal-overlay" @click.self="emit('close')">
    <div
      class="source-document-modal"
      :class="{ 'source-document-modal--wide': current?.page.screenshot_url }"
      role="dialog"
      aria-modal="true"
      aria-labelledby="source-document-modal-title"
    >
      <header class="source-document-modal__header">
        <h2 id="source-document-modal-title" class="source-document-modal__title">
          {{ documentName }}<span v-if="pageNumber"> — page {{ current?.page.page_number ?? pageNumber }}</span>
        </h2>
        <button type="button" class="source-document-modal__close" aria-label="Fermer" @click="emit('close')">
          ✕
        </button>
      </header>

      <div class="source-document-modal__body">
        <section v-if="excerpt" class="source-document-modal__excerpt">
          <h3 class="source-document-modal__section-title">Extrait cité</h3>
          <p class="source-document-modal__excerpt-text">{{ excerpt }}</p>
        </section>

        <nav v-if="cited.length > 1" class="source-document-modal__pager" aria-label="Pages citées">
          <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" :disabled="index === 0" @click="index--">
            Page précédente
          </button>
          <span class="source-document-modal__pager-count" aria-live="polite">
            Page {{ index + 1 }} sur {{ cited.length }} citées
          </span>
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm"
            :disabled="index === cited.length - 1"
            @click="index++"
          >
            Page suivante
          </button>
        </nav>

        <section>
          <h3 class="source-document-modal__section-title">Page source</h3>
          <p v-if="!pageNumber" class="source-document-modal__empty">
            Cette source n'est pas liée à une page précise du document.
          </p>
          <p v-else-if="loading" class="source-document-modal__empty">Chargement…</p>
          <p v-else-if="pageError" class="source-document-modal__error">Impossible de charger cette page.</p>
          <div
            v-else-if="current"
            class="source-document-modal__page"
            :class="{ 'source-document-modal__page--with-image': current.page.screenshot_url }"
          >
            <img
              v-if="current.page.screenshot_url"
              :src="`${API_BASE_URL}${current.page.screenshot_url}`"
              :alt="`Page ${current.page.page_number}`"
              class="source-document-modal__screenshot"
            />
            <div class="source-document-modal__text">
              <h4 v-if="current.page.screenshot_url" class="source-document-modal__section-title">
                Texte de la page
              </h4>
              <p v-if="!current.page.content" class="source-document-modal__empty">
                Aucun texte extrait pour cette page.
              </p>
              <p v-else class="source-document-modal__page-content">
                <template v-for="(segment, position) in current.match.segments" :key="position">
                  <mark v-if="segment.highlighted" class="source-document-modal__mark"
                    ><span class="source-document-modal__sr-only">[passage cité : </span>{{ segment.text
                    }}<span class="source-document-modal__sr-only">]</span></mark
                  >
                  <template v-else>{{ segment.text }}</template>
                </template>
              </p>
              <p
                v-if="excerpt && !current.match.matched"
                class="source-document-modal__empty source-document-modal__not-found"
              >
                Le passage cité n'a pas été retrouvé tel quel dans cette page.
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.source-document-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.source-document-modal {
  width: 100%;
  max-width: 34rem;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.source-document-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.source-document-modal__title {
  margin: 0;
  font-size: 1.0625rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-document-modal__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.source-document-modal__body {
  padding: 1.25rem 1.5rem 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.source-document-modal__section-title {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.source-document-modal__excerpt-text {
  margin: 0;
  padding: 0.75rem;
  border-radius: 0.5rem;
  background: var(--background-alt-blue-france);
  font-size: 0.875rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.source-document-modal__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.source-document-modal__error {
  color: var(--text-default-error);
  font-size: 0.875rem;
}

.source-document-modal__screenshot {
  display: block;
  width: 100%;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
}

.source-document-modal__page-content {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.6;
  white-space: pre-wrap;
}
.source-document-modal--wide {
  max-width: 62rem;
}

.source-document-modal__pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.source-document-modal__pager-count {
  font-size: 0.875rem;
}

.source-document-modal__page {
  display: grid;
  gap: 1.25rem;
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 768px) {
  .source-document-modal__page--with-image {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}

/* The cited passage: a background and an underline, so that it does not rely on colour alone. */
.source-document-modal__mark {
  background: var(--background-contrast-warning, #ffe9a8);
  color: inherit;
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 2px;
}

.source-document-modal__not-found {
  margin-top: 0.75rem;
}

.source-document-modal__sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
