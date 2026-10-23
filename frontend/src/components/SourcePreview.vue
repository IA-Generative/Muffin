<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchPageRects, rectStyle, type PageRect } from '../composables/usePageHighlights'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// The thumbnail of a cited page, with the passage framed (#350): what the source card shows before it is opened.
// Shown only when the page has a screenshot; a page without one (a URL, a Markdown file) has no thumbnail.
const props = defineProps<{
  collectionId: string
  documentId: string
  pageNumber: number
  passage?: string
}>()

const screenshotUrl = ref<string | null>(null)
const rects = ref<PageRect[]>([])
const failed = ref(false)

onMounted(async () => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/pages` +
        `?page=${props.pageNumber}&page_size=1`,
      { credentials: 'include' },
    )
    if (!response.ok) return
    const body: { items: { page_number: number; screenshot_url: string | null }[] } = await response.json()
    screenshotUrl.value = body.items[0]?.screenshot_url ?? null
  } catch {
    return
  }
  if (screenshotUrl.value) rects.value = await fetchPageRects(props.collectionId, props.documentId, props.pageNumber, props.passage)
})
</script>

<template>
  <span v-if="screenshotUrl && !failed" class="source-preview">
    <img
      :src="`${API_BASE_URL}${screenshotUrl}`"
      alt=""
      class="source-preview__image"
      loading="lazy"
      @error="failed = true"
    />
    <span
      v-for="(rect, index) in rects"
      :key="index"
      class="source-preview__frame"
      :style="rectStyle(rect)"
      aria-hidden="true"
    />
  </span>
</template>

<style scoped>
.source-preview {
  position: relative;
  display: block;
  line-height: 0;
  margin-top: 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  overflow: hidden;
}

.source-preview__image {
  display: block;
  width: 100%;
  height: auto;
}

.source-preview__frame {
  position: absolute;
  border: 2px solid var(--border-plain-warning, #d1b781);
  background: rgba(255, 224, 70, 0.3);
  border-radius: 2px;
  pointer-events: none;
}
</style>
