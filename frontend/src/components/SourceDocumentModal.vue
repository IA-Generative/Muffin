<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchChunkHighlights, fetchSourceRects, rectStyle, type PageRect } from '../composables/usePageHighlights'
import { documentFileUrl, hasFile, opensAtPage, pageWithin } from '../utils/documentFile'
import { highlightPassage, highlightRange, highlightRanges, type PassageMatch } from '../utils/highlightPassage'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// A passage that goes on over a page break is followed onto the next pages, up to this many more.
const MAX_FOLLOWING_PAGES = 4
// A cited chunk is shown on at most this many pages.
const MAX_CITED_PAGES = 8

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
  // The cited chunk (#353): the backend knows where it is in each page it touches, and says which pages - exact,
  // even when the same words are there twice, and no search of the text.
  chunkId?: string
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

// A page the reader went to that is not one of the cited ones (they move through the whole document, not only the
// pages the passage is on): shown plainly, with no frame and no highlight.
const browsed = ref<CitedPage | null>(null)
// How many pages the document has - known once a page has been read.
const total = ref<number>()
const pageInput = ref('')

const current = computed(() => browsed.value ?? cited.value[index.value])
const shownNumber = computed(() => current.value?.page.page_number ?? props.pageNumber ?? 1)

const fileAvailable = computed(() => hasFile(props.documentName))
const downloadUrl = computed(() => documentFileUrl(API_BASE_URL, props.collectionId, props.documentId))
const openUrl = computed(() =>
  documentFileUrl(API_BASE_URL, props.collectionId, props.documentId, { inline: true, page: shownNumber.value }),
)

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
  const body: { items: DocumentPage[]; total?: number } = await response.json()
  if (body.total !== undefined) total.value = body.total
  return body.items[0]
}

// Moves to a page of the document: one of the cited pages keeps its frames and its highlight, any other is shown as it is.
async function goTo(target: number | undefined) {
  if (target === undefined || (total.value !== undefined && (target < 1 || target > total.value))) return
  pageError.value = false
  const citedAt = cited.value.findIndex((entry) => entry.page.page_number === target)
  if (citedAt >= 0) {
    index.value = citedAt
    browsed.value = null
    return
  }
  try {
    const page = await fetchPage(target)
    if (page) browsed.value = { page, match: highlightPassage(page.content, undefined), rects: [] }
  } catch {
    pageError.value = true
  }
}

function goToTyped() {
  const target = pageWithin(pageInput.value, total.value ?? 0)
  if (target !== undefined) void goTo(target)
  pageInput.value = ''
}

// A source with no page of its own: the reader can still go through the document, from its first page.
async function startReading() {
  loading.value = true
  try {
    await goTo(1)
  } finally {
    loading.value = false
  }
}

// The zones to frame come after the page itself: the text is shown at once, the frames when they arrive.
async function framePage(position: number) {
  const entry = cited.value[position]
  if (!entry?.page.screenshot_url) return
  const rects = await fetchSourceRects(props.collectionId, props.documentId, entry.page.page_number, {
    passage: props.excerpt,
    start: props.start,
    end: props.end,
    chunkId: props.chunkId,
  })
  const current = cited.value[position]
  if (current === entry) cited.value = cited.value.map((item, at) => (at === position ? { ...item, rects } : item))
}

// A cited chunk: the backend says which pages it is on, and where in each - the pages are then shown with the
// passage highlighted and framed at that place. False when it cannot (it does not answer, or the chunk is not
// there): the passage is then looked for by its text.
async function loadChunk(chunkId: string, pageNumber: number): Promise<boolean> {
  const located = await fetchChunkHighlights(props.collectionId, props.documentId, pageNumber, chunkId)
  if (!located) return false
  const numbers = [...new Set([pageNumber, ...located.pages])].sort((a, b) => a - b).slice(0, MAX_CITED_PAGES)
  const entries: CitedPage[] = []
  for (const number of numbers) {
    const page = await fetchPage(number)
    if (!page) continue
    const here = number === pageNumber ? located : await fetchChunkHighlights(props.collectionId, props.documentId, number, chunkId)
    const match = here?.ranges.length ? highlightRanges(page.content, here.ranges) : highlightPassage(page.content, props.excerpt)
    // A page of the chunk's range that the passage is not on is not a cited page - except the one cited.
    if (match.matched || number === pageNumber) entries.push({ page, match, rects: here?.rects ?? [] })
  }
  if (!entries.length) return false
  cited.value = entries
  index.value = Math.max(entries.findIndex((entry) => entry.page.page_number === pageNumber), 0)
  return true
}

onMounted(async () => {
  if (!props.pageNumber) {
    loading.value = false
    return
  }
  try {
    if (props.chunkId && (await loadChunk(props.chunkId, props.pageNumber))) return
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
        <div v-if="fileAvailable" class="source-document-modal__actions">
          <a class="fr-btn fr-btn--tertiary fr-btn--sm" :href="downloadUrl" download>Télécharger le fichier</a>
          <a
            v-if="opensAtPage(documentName)"
            class="fr-btn fr-btn--tertiary fr-btn--sm"
            :href="openUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            Ouvrir à la page {{ shownNumber }}
          </a>
        </div>
        <button type="button" class="source-document-modal__close" aria-label="Fermer" @click="emit('close')">
          ✕
        </button>
      </header>

      <div class="source-document-modal__body">
        <!-- What a caller adds above the page: the navigation between the occurrences of an entity (#352). -->
        <slot name="extra" />

        <section v-if="excerpt" class="source-document-modal__excerpt">
          <h3 class="source-document-modal__section-title">Extrait cité</h3>
          <p class="source-document-modal__excerpt-text">{{ excerpt }}</p>
        </section>

        <nav v-if="total && total > 1" class="source-document-modal__pager" aria-label="Pages du document">
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm"
            :disabled="shownNumber <= 1"
            @click="goTo(shownNumber - 1)"
          >
            Page précédente
          </button>
          <span class="source-document-modal__pager-count" aria-live="polite">Page {{ shownNumber }} sur {{ total }}</span>
          <button
            type="button"
            class="fr-btn fr-btn--tertiary fr-btn--sm"
            :disabled="shownNumber >= total"
            @click="goTo(shownNumber + 1)"
          >
            Page suivante
          </button>
          <label class="source-document-modal__goto">
            Aller à la page
            <input
              v-model="pageInput"
              type="number"
              min="1"
              :max="total"
              inputmode="numeric"
              class="fr-input source-document-modal__goto-input"
              @keydown.enter.prevent="goToTyped"
            />
          </label>
        </nav>
        <p v-if="cited.length > 1" class="source-document-modal__cited-pages">
          Pages citées :
          <button
            v-for="entry in cited"
            :key="entry.page.page_number"
            type="button"
            class="source-document-modal__cited-page"
            :class="{ 'source-document-modal__cited-page--current': entry.page.page_number === shownNumber }"
            :aria-current="entry.page.page_number === shownNumber ? 'page' : undefined"
            @click="goTo(entry.page.page_number)"
          >
            {{ entry.page.page_number }}
          </button>
        </p>

        <section>
          <h3 class="source-document-modal__section-title">Page source</h3>
          <p v-if="!pageNumber && !current" class="source-document-modal__empty">
            Cette source n'est pas liée à une page précise du document.
            <button
              v-if="fileAvailable"
              type="button"
              class="fr-btn fr-btn--tertiary fr-btn--sm"
              :disabled="loading"
              @click="startReading"
            >
              Parcourir le document
            </button>
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
                v-if="excerpt && !browsed && !current.match.matched"
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
.source-document-modal__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-left: auto;
  margin-right: 0.5rem;
}

.source-document-modal__goto {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
}

.source-document-modal__goto-input {
  width: 5rem;
  padding: 0.25rem 0.5rem;
}

.source-document-modal__cited-pages {
  margin: 0.5rem 0 0;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.source-document-modal__cited-page {
  min-width: 1.75rem;
  margin-left: 0.25rem;
  padding: 0.125rem 0.375rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  color: var(--text-action-high-blue-france);
  cursor: pointer;
}

.source-document-modal__cited-page--current {
  background: var(--background-action-low-blue-france);
  font-weight: 700;
}

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
  /* The figure is a grid item beside the page's text: stretched to the height of a long text, it would be
     taller than the screenshot, and the frames, laid out in percent of the figure, would slide down it. */
  align-self: start;
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
