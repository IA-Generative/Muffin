<script setup lang="ts">
import { onMounted, ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const props = defineProps<{
  collectionId: string
  documentId: string
  documentName: string
  pageNumber?: number
  // The exact chunk text that was actually retrieved and cited - already in hand from the
  // citation itself, never refetched.
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

const page = ref<DocumentPage>()
const pageError = ref(false)
const loading = ref(true)

onMounted(async () => {
  if (!props.pageNumber) {
    loading.value = false
    return
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.documentId}/pages` +
        `?page=${props.pageNumber}&page_size=1`,
      { credentials: 'include' },
    )
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { items: DocumentPage[] } = await response.json()
    page.value = body.items[0]
  } catch {
    pageError.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="source-document-modal-overlay" @click.self="emit('close')">
    <div class="source-document-modal" role="dialog" aria-modal="true" aria-labelledby="source-document-modal-title">
      <header class="source-document-modal__header">
        <h2 id="source-document-modal-title" class="source-document-modal__title">
          {{ documentName }}<span v-if="pageNumber"> — page {{ pageNumber }}</span>
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

        <section>
          <h3 class="source-document-modal__section-title">Page source</h3>
          <p v-if="!pageNumber" class="source-document-modal__empty">
            Cette source n'est pas liée à une page précise du document.
          </p>
          <p v-else-if="loading" class="source-document-modal__empty">Chargement…</p>
          <p v-else-if="pageError" class="source-document-modal__error">Impossible de charger cette page.</p>
          <template v-else-if="page">
            <img
              v-if="page.screenshot_url"
              :src="`${API_BASE_URL}${page.screenshot_url}`"
              :alt="`Page ${page.page_number}`"
              class="source-document-modal__screenshot"
            />
            <p v-else class="source-document-modal__page-content">{{ page.content }}</p>
          </template>
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
</style>
