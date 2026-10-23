<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchSourceRects, rectStyle, type PageRect } from '../composables/usePageHighlights'
import { highlightPassage, highlightRange, type PassageMatch } from '../utils/highlightPassage'

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
  // Where that passage is in the page's text (#351), when it is known - a question-answer pair remembers it:
  // highlighted and framed exactly, even when the same words are there twice. Without it, the passage is
  // looked for by its text.
  start?: number
  end?: number
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
  // Where the passage is on the page's screenshot, to frame (#350) - none when it is not known.
  rects: PageRect[]
}

// The pages the passage is on - the cited one, and the next ones when it goes on over the page break.
const cited = ref<CitedPage[]>([])
const index = ref(0)
const pageError = ref(false)
const loading = ref(true)

const current = computed(() => cited.value[index.value])

// The passage in a page's text: at its interval when it is known and it is in the page, else by its text.
function highlight(content: string, pageNumber: number): PassageMatch {
  if (props.start !== undefined && props.end !== undefined && pageNumber === props.pageNumber) {
    const exact = highlightRange(content, props.start, props.end)
    if (exact.matched) return exact
  }
  return highlightPassage(content, props.excerpt)
}

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

// The zones to frame come after the page itself: the text is shown at once, the frames when they arrive.
async function framePage(position: number) {
  const entry = cited.value[position]
  if (!entry?.page.screenshot_url) return
  const rects = await fetchSourceRects(props.collectionId, props.documentId, entry.page.page_number, {
    passage: props.excerpt,
    start: props.start,
    end: props.end,
  })
  const current = cited.value[position]
  if (current === entry) cited.value = cited.value.map((item, at) => (at === position ? { ...item, rects } : item))
}

onMounted(async () => {
  if (!props.pageNumber) {
    loading.value = false
    return
  }
  try {
    const first = await fetchPage(props.pageNumber)
    if (first) {
      let match = highlight(first.content, first.page_number)
      cited.value = [{ page: first, match, rects: [] }]
      void framePage(0)
      // The last fragment of the passage is not on this page: it goes on over the page break.
      for (let step = 1; step <= MAX_FOLLOWING_PAGES && match.matched && !match.lastFound; step++) {
        const next = await fetchPage(props.pageNumber + step)
        if (!next) break
        match = highlight(next.content, next.page_number)
        if (!match.matched) break
        cited.value = [...cited.value, { page: next, match, rects: [] }]
        void framePage(cited.value.length - 1)
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
            <div v-if="current.page.screenshot_url" class="source-document-modal__figure">
              <img
                :src="`${API_BASE_URL}${current.page.screenshot_url}`"
                :alt="`Page ${current.page.page_number}`"
                class="source-document-modal__screenshot"
              />
              <!-- The cited zones, framed on the page (the passage is also given as text beside it). -->
              <span
                v-for="(rect, position) in current.rects"
                :key="position"
                class="source-document-modal__frame"
                :style="rectStyle(rect)"
                aria-hidden="true"
              />
            </div>
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

.source-document-modal__figure {
  position: relative;
  line-height: 0;
}

/* A cited zone: framed on the page, in percent of the image. */
.source-document-modal__frame {
  position: absolute;
  border: 2px solid var(--border-plain-warning, #d1b781);
  background: rgba(255, 224, 70, 0.3);
  border-radius: 2px;
  pointer-events: none;
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
