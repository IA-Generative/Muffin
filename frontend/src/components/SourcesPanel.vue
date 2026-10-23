<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Source } from '../types/chat'
import { formatPath } from '../utils/collectionPath'
import SourceDocumentModal from './SourceDocumentModal.vue'
import SourcePreview from './SourcePreview.vue'

defineProps<{
  sources: Source[]
}>()

defineEmits<{
  close: []
}>()

const openSource = ref<Source>()

// What the modal opens on: the cited page of a document, or - for a cited question-answer pair - the page its
// answer comes from, with the passage (#351).
const modal = computed(() => {
  const source = openSource.value
  if (!source?.collectionId) return undefined
  if (source.type === 'qa' && source.qaSource) {
    const { documentId, documentName, pageNumber, passage, start, end } = source.qaSource
    return {
      collectionId: source.collectionId,
      documentId,
      documentName,
      pageNumber,
      excerpt: passage,
      start,
      end,
      chunkId: undefined,
    }
  }
  if (!source.documentId) return undefined
  return {
    collectionId: source.collectionId,
    documentId: source.documentId,
    documentName: source.title,
    pageNumber: source.pageNumber,
    excerpt: source.content,
    start: undefined,
    end: undefined,
    chunkId: source.chunkId,
  }
})
</script>

<template>
  <aside class="sources-panel">
    <div class="sources-panel__header">
      <h2>Sources</h2>
      <button type="button" class="sources-panel__close" aria-label="Fermer" @click="$emit('close')">
        ✕
      </button>
    </div>

    <ul class="sources-panel__list">
      <li v-for="source in sources" :key="source.url ?? source.title" class="sources-panel__item">
        <!-- Document card: links back to a real page - clickable, opens the page+chunk modal. -->
        <button
          v-if="source.type === 'document'"
          type="button"
          class="sources-panel__card sources-panel__card--document"
          @click="openSource = source"
        >
          <span class="sources-panel__card-kind">Document</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <span v-if="source.collectionPath" class="sources-panel__meta">{{ formatPath(source.collectionPath) }}</span>
          <span v-if="source.revision" class="sources-panel__meta">Révision {{ source.revision }}</span>
          <span v-if="source.pageNumber" class="sources-panel__meta">Page {{ source.pageNumber }}</span>
          <!-- The cited page, with the passage framed (#350) - only when the page has a screenshot. -->
          <SourcePreview
            v-if="source.collectionId && source.documentId && source.pageNumber"
            :collection-id="source.collectionId"
            :document-id="source.documentId"
            :page-number="source.pageNumber"
            :passage="source.content"
            :chunk-id="source.chunkId"
          />
        </button>

        <!-- Document summary card: a collection-level summary, not a specific page - shown as
             read-only text (no page to open). -->
        <div
          v-else-if="source.type === 'document_summary'"
          class="sources-panel__card sources-panel__card--summary"
        >
          <span class="sources-panel__card-kind">Résumé</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <p v-if="source.content" class="sources-panel__tool-line">{{ source.content }}</p>
        </div>

        <!-- QA card: a previously-answered question reused as evidence. When the pair knows the page and
             passage its answer comes from (#351), it opens that page with the passage framed. -->
        <button
          v-else-if="source.type === 'qa' && source.qaSource"
          type="button"
          class="sources-panel__card sources-panel__card--qa"
          :aria-label="`Voir la source de cette réponse dans ${source.qaSource.documentName}, page ${source.qaSource.pageNumber}`"
          @click="openSource = source"
        >
          <span class="sources-panel__card-kind">Question déjà répondue</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <p v-if="source.content" class="sources-panel__tool-line">{{ source.content }}</p>
          <span class="sources-panel__meta">{{ source.qaSource.documentName }} · page {{ source.qaSource.pageNumber }}</span>
          <SourcePreview
            v-if="source.collectionId"
            :collection-id="source.collectionId"
            :document-id="source.qaSource.documentId"
            :page-number="source.qaSource.pageNumber"
            :passage="source.qaSource.passage"
            :start="source.qaSource.start"
            :end="source.qaSource.end"
          />
        </button>
        <div v-else-if="source.type === 'qa'" class="sources-panel__card sources-panel__card--qa">
          <span class="sources-panel__card-kind">Question déjà répondue</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <p v-if="source.content" class="sources-panel__tool-line">{{ source.content }}</p>
        </div>

        <!-- Collection card: a knowledge-base-level meta-fact (collection description, document
             count) - read-only, no page to open. -->
        <div
          v-else-if="source.type === 'collection'"
          class="sources-panel__card sources-panel__card--collection"
        >
          <span class="sources-panel__card-kind">Base de connaissances</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <p v-if="source.content" class="sources-panel__tool-line">{{ source.content }}</p>
        </div>

        <!-- Tool card: a knowledge-base lookup, not a document - just its input/output, nothing
             to open a page for. -->
        <div v-else-if="source.type === 'tool'" class="sources-panel__card sources-panel__card--tool">
          <span class="sources-panel__card-kind">Outil</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <p v-if="source.query" class="sources-panel__tool-line">
            <span class="sources-panel__tool-label">Entrée</span>{{ source.query }}
          </p>
          <p v-if="source.content" class="sources-panel__tool-line">
            <span class="sources-panel__tool-label">Sortie</span>{{ source.content }}
          </p>
        </div>

        <!-- Web card: the web_search tool - a real external link, opens in a new tab. -->
        <a
          v-else-if="source.type === 'web' && source.url"
          :href="source.url"
          target="_blank"
          rel="noopener noreferrer"
          class="sources-panel__card sources-panel__card--web"
        >
          <span class="sources-panel__card-kind">Web</span>
          <span class="sources-panel__title">{{ source.title }}</span>
          <span class="sources-panel__url">{{ source.url }}</span>
        </a>

        <!-- Older citation with no type info, or a user-added feedback source. -->
        <a v-else-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="sources-panel__card">
          <span class="sources-panel__title">{{ source.title }}</span>
          <span class="sources-panel__url">{{ source.url }}</span>
        </a>
        <div v-else class="sources-panel__card">
          <span class="sources-panel__title">{{ source.title }}</span>
        </div>
      </li>
    </ul>

    <SourceDocumentModal
      v-if="modal"
      :collection-id="modal.collectionId"
      :document-id="modal.documentId"
      :document-name="modal.documentName"
      :page-number="modal.pageNumber"
      :excerpt="modal.excerpt"
      :start="modal.start"
      :end="modal.end"
      :chunk-id="modal.chunkId"
      @close="openSource = undefined"
    />
  </aside>
</template>

<style scoped>
.sources-panel {
  width: 320px;
  flex-shrink: 0;
  height: 100%;
  padding: 1.25rem;
  background: var(--background-alt-grey);
  border-left: 1px solid var(--border-default-grey);
  box-sizing: border-box;
  overflow-y: auto;
}

.sources-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sources-panel__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.sources-panel__close {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-mention-grey);
}

.sources-panel__list {
  list-style: none;
  margin: 1rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.sources-panel__card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  width: 100%;
  padding: 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  text-decoration: none;
  text-align: left;
  font: inherit;
  color: inherit;
  cursor: default;
  box-sizing: border-box;
}

.sources-panel__card--document {
  cursor: pointer;
}

.sources-panel__card--document:hover {
  border-color: var(--border-action-high-blue-france);
}

a.sources-panel__card:hover {
  border-color: var(--border-action-high-blue-france);
}

.sources-panel__card-kind {
  align-self: flex-start;
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.sources-panel__card--document .sources-panel__card-kind {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.sources-panel__card--summary .sources-panel__card-kind {
  background: var(--background-alt-purple, var(--background-alt-grey));
  color: var(--text-action-high-purple, var(--text-mention-grey));
}

.sources-panel__card--qa .sources-panel__card-kind {
  background: var(--background-alt-yellow-tournesol, var(--background-alt-grey));
  color: var(--text-action-high-yellow-tournesol, var(--text-mention-grey));
}

.sources-panel__card--collection .sources-panel__card-kind {
  background: var(--background-alt-blue-ecume, var(--background-alt-grey));
  color: var(--text-action-high-blue-ecume, var(--text-mention-grey));
}

.sources-panel__card--web:hover {
  border-color: var(--border-action-high-blue-france);
}

.sources-panel__card--web .sources-panel__card-kind {
  background: var(--background-alt-green-emeraude, var(--background-alt-grey));
  color: var(--text-default-success, var(--text-default-grey));
}

.sources-panel__title {
  color: var(--text-action-high-blue-france);
  font-weight: 700;
}

.sources-panel__card--tool .sources-panel__title {
  color: var(--text-default-grey);
}

.sources-panel__meta {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.sources-panel__url {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sources-panel__tool-line {
  margin: 0;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: var(--text-mention-grey);
}

.sources-panel__tool-label {
  display: inline-block;
  margin-right: 0.375rem;
  font-weight: 700;
  color: var(--text-default-grey);
}
</style>
