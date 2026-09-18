<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { CollectionDocument, Entity, EntityType, QaPair, Relation } from '../types/collection'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const props = defineProps<{
  collectionId: string
  document: CollectionDocument
}>()

const emit = defineEmits<{
  close: []
}>()

interface DocumentDetail {
  id: string
  name: string
  type: string
  status: string
  progress: number
  summary: string | null
  error: string | null
  tags: string[]
  page_count: number
}

interface DocumentPage {
  page_number: number
  content: string
  screenshot_url: string | null
}

type Tab = 'summary' | 'entities' | 'qa'

const activeTab = ref<Tab>('summary')

const detail = ref<DocumentDetail>()
const detailError = ref(false)

const pages = ref<DocumentPage[]>([])
const pageNumber = ref(1)
const pageTotal = ref(0)
const pagesLoading = ref(false)
const pagesError = ref(false)

const qaPairs = ref<QaPair[]>()
const qaError = ref(false)

const entities = ref<Entity[]>()
const relations = ref<Relation[]>()
const entitiesError = ref(false)

const ENTITY_LABEL: Record<EntityType, string> = {
  personne: 'Personne',
  organisation: 'Organisation',
  lieu: 'Lieu',
  date: 'Date',
  autre: 'Autre',
}

async function loadDetail() {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.document.id}`,
      { credentials: 'include' },
    )
    if (!response.ok) throw new Error(`${response.status}`)
    detail.value = await response.json()
  } catch {
    detailError.value = true
  }
}

async function loadPage(page: number) {
  pagesLoading.value = true
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.document.id}/pages` +
        `?page=${page}&page_size=1`,
      { credentials: 'include' },
    )
    if (!response.ok) throw new Error(`${response.status}`)
    const body: { items: DocumentPage[]; total: number } = await response.json()
    pages.value = body.items
    pageTotal.value = body.total
  } catch {
    pagesError.value = true
  } finally {
    pagesLoading.value = false
  }
}

async function loadQaPairs() {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${props.collectionId}/qa-pairs?document_id=${props.document.id}`,
      { credentials: 'include' },
    )
    if (!response.ok) throw new Error(`${response.status}`)
    qaPairs.value = await response.json()
  } catch {
    qaError.value = true
  }
}

async function loadEntitiesAndRelations() {
  try {
    const [entitiesResponse, relationsResponse] = await Promise.all([
      fetch(`${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.document.id}/entities`, {
        credentials: 'include',
      }),
      fetch(`${API_BASE_URL}/api/collections/${props.collectionId}/documents/${props.document.id}/relations`, {
        credentials: 'include',
      }),
    ])
    if (!entitiesResponse.ok || !relationsResponse.ok) throw new Error('failed')
    entities.value = await entitiesResponse.json()
    relations.value = await relationsResponse.json()
  } catch {
    entitiesError.value = true
  }
}

// The right-hand tabs' data is fetched lazily, the first time each is opened; the pages panel on
// the left is always visible instead, so it loads eagerly on mount alongside the summary.
const loadedTabs = new Set<Tab>()
watch(
  activeTab,
  (tab) => {
    if (loadedTabs.has(tab)) return
    loadedTabs.add(tab)
    if (tab === 'qa') loadQaPairs()
    if (tab === 'entities') loadEntitiesAndRelations()
  },
  { immediate: true },
)

watch(pageNumber, (page) => loadPage(page))

onMounted(() => {
  loadDetail()
  loadPage(1)
})
</script>

<template>
  <div class="document-modal-overlay" @click.self="emit('close')">
    <div class="document-modal" role="dialog" aria-modal="true" aria-labelledby="document-modal-title">
      <header class="document-modal__header">
        <h2 id="document-modal-title" class="document-modal__title">{{ document.name }}</h2>
        <button type="button" class="document-modal__close" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>

      <div class="document-modal__content">
        <aside class="document-modal__pages-panel">
          <p v-if="pagesError" class="document-modal__error">Impossible de charger les pages.</p>
          <template v-else-if="!pagesLoading && pageTotal === 0">
            <p class="document-modal__empty">Aucune page indexée pour le moment.</p>
          </template>
          <template v-else>
            <p v-if="pagesLoading" class="document-modal__loading">Chargement…</p>
            <template v-else-if="pages[0]">
              <img
                v-if="pages[0].screenshot_url"
                :src="`${API_BASE_URL}${pages[0].screenshot_url}`"
                :alt="`Page ${pages[0].page_number}`"
                class="document-modal__screenshot"
              />
              <p v-else class="document-modal__page-content">{{ pages[0].content }}</p>
            </template>
            <div class="document-modal__pagination">
              <button type="button" :disabled="pageNumber === 1" @click="pageNumber--">Précédent</button>
              <span>Page {{ pageNumber }} / {{ pageTotal }}</span>
              <button type="button" :disabled="pageNumber === pageTotal" @click="pageNumber++">Suivant</button>
            </div>
          </template>
        </aside>

        <div class="document-modal__right">
          <nav class="document-modal__tabs" aria-label="Sections du document">
            <button
              type="button"
              class="document-modal__tab"
              :class="{ 'document-modal__tab--active': activeTab === 'summary' }"
              @click="activeTab = 'summary'"
            >
              Résumé
            </button>
            <button
              type="button"
              class="document-modal__tab"
              :class="{ 'document-modal__tab--active': activeTab === 'entities' }"
              @click="activeTab = 'entities'"
            >
              Entités &amp; relations
            </button>
            <button
              type="button"
              class="document-modal__tab"
              :class="{ 'document-modal__tab--active': activeTab === 'qa' }"
              @click="activeTab = 'qa'"
            >
              Questions/réponses
            </button>
          </nav>

          <div class="document-modal__body">
            <section v-if="activeTab === 'summary'">
              <p v-if="detailError" class="document-modal__error">Impossible de charger ce document.</p>
              <template v-else-if="detail">
                <div v-if="detail.tags.length" class="document-modal__tags">
                  <span v-for="tag in detail.tags" :key="tag" class="document-modal__tag">{{ tag }}</span>
                </div>
                <p v-if="detail.summary" class="document-modal__summary">{{ detail.summary }}</p>
                <p v-else class="document-modal__empty">Aucun résumé disponible pour le moment.</p>
                <p v-if="detail.error" class="document-modal__processing-error">{{ detail.error }}</p>
                <p class="document-modal__meta">{{ detail.page_count }} page(s)</p>
              </template>
              <p v-else class="document-modal__loading">Chargement…</p>
            </section>

            <section v-else-if="activeTab === 'entities'">
              <p v-if="entitiesError" class="document-modal__error">
                Impossible de charger les entités et relations.
              </p>
              <template v-else-if="entities && relations">
                <h3 class="document-modal__section-title">Entités</h3>
                <ul v-if="entities.length" class="document-modal__entities">
                  <li v-for="entity in entities" :key="entity.id" class="document-modal__entity">
                    <span class="document-modal__entity-type" :class="`document-modal__entity-type--${entity.type}`">
                      {{ ENTITY_LABEL[entity.type] }}
                    </span>
                    <span>{{ entity.name }}</span>
                    <span class="document-modal__entity-mentions">{{ entity.mentions }} mention(s)</span>
                  </li>
                </ul>
                <p v-else class="document-modal__empty">Aucune entité détectée dans ce document.</p>

                <h3 class="document-modal__section-title">Relations</h3>
                <ul v-if="relations.length" class="document-modal__relations">
                  <li v-for="relation in relations" :key="relation.id" class="document-modal__relation">
                    <span>{{ relation.from }}</span>
                    <span class="document-modal__relation-type">{{ relation.type }}</span>
                    <span>{{ relation.to }}</span>
                  </li>
                </ul>
                <p v-else class="document-modal__empty">Aucune relation détectée dans ce document.</p>
              </template>
              <p v-else class="document-modal__loading">Chargement…</p>
            </section>

            <section v-else-if="activeTab === 'qa'">
              <p v-if="qaError" class="document-modal__error">Impossible de charger les questions/réponses.</p>
              <template v-else-if="qaPairs">
                <ul v-if="qaPairs.length" class="document-modal__qa-list">
                  <li v-for="pair in qaPairs" :key="pair.id" class="document-modal__qa-item">
                    <span class="document-modal__qa-question">{{ pair.question }}</span>
                    <span class="document-modal__qa-answer">{{ pair.answer }}</span>
                  </li>
                </ul>
                <p v-else class="document-modal__empty">Aucune question/réponse générée pour ce document.</p>
              </template>
              <p v-else class="document-modal__loading">Chargement…</p>
            </section>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.document-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.document-modal {
  width: 100%;
  max-width: 64rem;
  height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.document-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.document-modal__title {
  margin: 0;
  font-size: 1.125rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-modal__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.document-modal__content {
  flex: 1;
  display: flex;
  min-height: 0;
  margin-top: 1rem;
}

.document-modal__pages-panel {
  flex: 0 0 40%;
  padding: 0 1.5rem 1.5rem;
  overflow-y: auto;
  border-right: 1px solid var(--border-default-grey);
}

.document-modal__right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.document-modal__tabs {
  display: flex;
  gap: 0.25rem;
  margin: 0 1.5rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.document-modal__tab {
  padding: 0.625rem 0.875rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font: inherit;
  font-size: 0.875rem;
}

.document-modal__tab--active {
  color: var(--text-action-high-blue-france);
  border-bottom-color: var(--border-action-high-blue-france);
  font-weight: 600;
}

.document-modal__body {
  flex: 1;
  padding: 1.25rem 1.5rem 1.5rem;
  overflow-y: auto;
}

.document-modal__loading,
.document-modal__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.document-modal__error {
  color: var(--text-default-error);
  font-size: 0.875rem;
}

.document-modal__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.875rem;
}

.document-modal__tag {
  font-size: 0.75rem;
  padding: 0.1875rem 0.625rem;
  border-radius: 1rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.document-modal__summary {
  font-size: 0.875rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.document-modal__processing-error {
  margin-top: 0.75rem;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.document-modal__meta {
  margin-top: 1rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.document-modal__screenshot {
  display: block;
  width: 100%;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
}

.document-modal__page-content {
  font-size: 0.875rem;
  line-height: 1.6;
  white-space: pre-wrap;
}

.document-modal__pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1rem;
}

.document-modal__pagination button {
  padding: 0.375rem 0.875rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
}

.document-modal__pagination button:disabled {
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}

.document-modal__pagination span {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.document-modal__section-title {
  margin: 1.25rem 0 0.5rem;
  font-size: 0.9375rem;
}

.document-modal__section-title:first-of-type {
  margin-top: 0;
}

.document-modal__entities,
.document-modal__relations,
.document-modal__qa-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.document-modal__entity,
.document-modal__relation {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  font-size: 0.8125rem;
}

.document-modal__entity-type {
  font-size: 0.6875rem;
  font-weight: 700;
  padding: 0.0625rem 0.5rem;
  border-radius: 0.75rem;
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.document-modal__entity-mentions {
  margin-left: auto;
  color: var(--text-mention-grey);
}

.document-modal__relation-type {
  color: var(--text-mention-grey);
  font-style: italic;
}

.document-modal__qa-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.document-modal__qa-question {
  font-weight: 700;
  font-size: 0.875rem;
}

.document-modal__qa-answer {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}
</style>
