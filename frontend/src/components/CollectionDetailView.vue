<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import type { Collection } from '../types/collection'
import CollectionChunksTab from './CollectionChunksTab.vue'
import CollectionDocumentsTab from './CollectionDocumentsTab.vue'
import CollectionEvaluationTab from './CollectionEvaluationTab.vue'
import CollectionQaTab from './CollectionQaTab.vue'
import CollectionRelationsTab from './CollectionRelationsTab.vue'
import CollectionSettingsTab from './CollectionSettingsTab.vue'

const props = defineProps<{
  collection: Collection
}>()

const { closeCollection, updateName, updateDescription, updateTags, deleteCollection, isCollectionReady } =
  useCollections()

const tagDraft = ref('')
const isReady = computed(() => isCollectionReady(props.collection))

type TabKey = 'documents' | 'qa' | 'evaluation' | 'relations' | 'chunks' | 'settings'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'settings', label: 'Paramètres' },
  { key: 'documents', label: 'Documents' },
  { key: 'qa', label: 'Questions / Réponses' },
  { key: 'evaluation', label: 'Évaluation' },
  { key: 'relations', label: 'Entités & Relations' },
  { key: 'chunks', label: 'Chunks' },
]
// Paramètres en premier : on configure le chunking/embedding avant d'ajouter
// des documents, donc c'est l'onglet le plus utile à l'ouverture.
const activeTab = ref<TabKey>('settings')

// Tant que le nom et les paramètres n'ont pas été confirmés, on reste
// coincé sur l'onglet Paramètres - y compris si on y revient plus tard
// (changement de collection active, navigation directe par URL).
watch(
  () => [props.collection.id, isReady.value],
  () => {
    if (!isReady.value) activeTab.value = 'settings'
  },
  { immediate: true },
)

function selectTab(key: TabKey) {
  if (key !== 'settings' && !isReady.value) return
  activeTab.value = key
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatStamp(meta: { updatedBy: string; updatedAt: string } | null) {
  if (!meta) return ''
  return `Modifié par ${meta.updatedBy} le ${dateFormatter.format(new Date(meta.updatedAt))}`
}

function addTag() {
  const tag = tagDraft.value.trim()
  if (!tag || props.collection.tags.includes(tag)) return
  updateTags(props.collection.id, [...props.collection.tags, tag])
  tagDraft.value = ''
}

function removeTag(tag: string) {
  updateTags(props.collection.id, props.collection.tags.filter((item) => item !== tag))
}

function askDelete() {
  if (confirm(`Supprimer la collection "${props.collection.name}" ?`)) {
    deleteCollection(props.collection.id)
  }
}
</script>

<template>
  <section class="collection-detail">
    <div class="collection-detail__inner">
      <button type="button" class="collection-detail__back" @click="closeCollection()">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
        </svg>
        Collections
      </button>

      <div class="collection-detail__header">
        <input
          class="collection-detail__name"
          :value="collection.name"
          aria-label="Nom de la collection"
          @change="updateName(collection.id, ($event.target as HTMLInputElement).value)"
        />
        <button type="button" class="collection-detail__delete" @click="askDelete">Supprimer</button>
      </div>

      <textarea
        class="collection-detail__description"
        :value="collection.description"
        placeholder="Décrivez cette collection…"
        rows="2"
        aria-label="Description de la collection"
        @change="updateDescription(collection.id, ($event.target as HTMLTextAreaElement).value)"
      />
      <p v-if="collection.descriptionMeta" class="collection-detail__meta">
        {{ formatStamp(collection.descriptionMeta) }}
      </p>

      <div class="collection-detail__tags">
        <span v-for="tag in collection.tags" :key="tag" class="collection-detail__tag">
          {{ tag }}
          <button type="button" :aria-label="`Retirer le tag ${tag}`" @click="removeTag(tag)">✕</button>
        </span>
        <input
          v-model="tagDraft"
          type="text"
          class="collection-detail__tag-input"
          placeholder="+ tag"
          aria-label="Ajouter un tag"
          @keydown.enter.prevent="addTag"
          @blur="addTag"
        />
      </div>
      <p v-if="collection.tags.length" class="collection-detail__meta">{{ formatStamp(collection.tagsMeta) }}</p>

      <nav class="collection-detail__tabs" aria-label="Sections de la collection">
        <button
          v-for="tab in TABS"
          :key="tab.key"
          type="button"
          class="collection-detail__tab"
          :class="{ 'collection-detail__tab--active': activeTab === tab.key }"
          :disabled="tab.key !== 'settings' && !isReady"
          :title="tab.key !== 'settings' && !isReady ? 'Nommez la collection et enregistrez ses paramètres d\'abord' : undefined"
          @click="selectTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </nav>

      <p v-if="!isReady" class="collection-detail__gate-hint">
        Donnez un nom à cette collection et enregistrez ses paramètres de découpage et de modèle d'embedding
        avant d'ajouter des documents.
      </p>

      <div class="collection-detail__panel">
        <CollectionDocumentsTab v-if="activeTab === 'documents'" :collection="collection" />
        <CollectionQaTab v-else-if="activeTab === 'qa'" :collection="collection" />
        <CollectionEvaluationTab v-else-if="activeTab === 'evaluation'" :collection="collection" />
        <CollectionRelationsTab v-else-if="activeTab === 'relations'" :collection="collection" />
        <CollectionChunksTab v-else-if="activeTab === 'chunks'" :collection="collection" />
        <CollectionSettingsTab v-else :collection="collection" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.collection-detail {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.collection-detail__inner {
  max-width: 42rem;
  margin: 0 auto;
}

.collection-detail__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  padding: 0;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.collection-detail__back:hover {
  color: var(--text-default-grey);
}

.collection-detail__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.collection-detail__name {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text-default-grey);
  font-family: inherit;
  padding: 0.25rem 0;
}

.collection-detail__name:focus {
  outline: none;
  border-bottom: 2px solid var(--border-action-high-blue-france);
}

.collection-detail__delete {
  flex-shrink: 0;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  padding: 0.375rem 0.75rem;
  background: var(--background-default-grey);
  color: var(--text-default-error);
  cursor: pointer;
  font-size: 0.8125rem;
}

.collection-detail__description {
  width: 100%;
  margin-top: 0.75rem;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  font: inherit;
  resize: vertical;
  padding: 0;
}

.collection-detail__description:focus {
  outline: none;
}

.collection-detail__meta {
  margin: 0.375rem 0 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.collection-detail__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.collection-detail__tag {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  border-radius: 1rem;
  background: var(--background-alt-grey);
  font-size: 0.8125rem;
}

.collection-detail__tag button {
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 0.75rem;
}

.collection-detail__tag-input {
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  font: inherit;
  font-size: 0.8125rem;
  width: 5rem;
}

.collection-detail__tag-input:focus {
  outline: none;
}

.collection-detail__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 1.75rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.collection-detail__tab {
  padding: 0.625rem 0.25rem;
  margin-right: 1rem;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 0.875rem;
}

.collection-detail__tab:hover {
  color: var(--text-default-grey);
}

.collection-detail__tab--active {
  color: var(--text-action-high-blue-france);
  border-bottom-color: var(--border-action-high-blue-france);
  font-weight: 700;
}

.collection-detail__tab:disabled {
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}

.collection-detail__gate-hint {
  margin: 1rem 0 0;
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-orange-terre-battue, var(--background-alt-grey));
  font-size: 0.8125rem;
}

.collection-detail__panel {
  padding-top: 1.5rem;
}
</style>
