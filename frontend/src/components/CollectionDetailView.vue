<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCollections } from '../composables/useCollections'
import type { Collection } from '../types/collection'
import CollectionChunksTab from './CollectionChunksTab.vue'
import CollectionDocumentsTab from './CollectionDocumentsTab.vue'
import CollectionEvaluationTab from './CollectionEvaluationTab.vue'
import CollectionQaTab from './CollectionQaTab.vue'
import CollectionRelationsTab from './CollectionRelationsTab.vue'
import CollectionSettingsTab from './CollectionSettingsTab.vue'
import ConfirmDeleteModal from './ConfirmDeleteModal.vue'

const props = defineProps<{
  collection: Collection
  activeDocumentId?: string
}>()

const route = useRoute()
const router = useRouter()
const { closeCollection, updateName, updateDescription, updateTags, deleteCollection, isCollectionReady, loadTabData } =
  useCollections()

const tagDraft = ref('')
const isReady = computed(() => isCollectionReady(props.collection))

// §140: description + tags read as a single secondary block, collapsible so the header stays
// short once a collection is set up - expanded by default so nothing is hidden on first load.
const showDetails = ref(true)

// §142: explicit read/edit mode instead of permanently-editable-looking fields. Forced open while
// the collection isn't ready yet (same gating as the Paramètres tab lock below) since naming a
// freshly created collection is the first thing an owner needs to do - never add friction there.
const isEditingMeta = ref(!isReady.value)
watch(isReady, (ready) => {
  if (!ready) isEditingMeta.value = true
})
function toggleEditMeta() {
  isEditingMeta.value = !isEditingMeta.value
  if (isEditingMeta.value) showDetails.value = true
}

type TabKey = 'documents' | 'qa' | 'evaluation' | 'relations' | 'chunks' | 'settings'
// §141: seuls Paramètres/Documents/Questions-Réponses restent au premier niveau - le reste
// (Chunks, Entités & Relations, Évaluation) est regroupé sous le menu "Avancé" pour ne pas
// mettre au même niveau visuel l'essentiel et les vues d'analyse/debug. Les URLs par onglet
// (/collections/:id/chunks etc.) restent inchangées pour ne pas casser de lien existant.
const PRIMARY_TABS: { key: TabKey; label: string }[] = [
  { key: 'settings', label: 'Paramètres' },
  { key: 'documents', label: 'Documents' },
  { key: 'qa', label: 'Questions / Réponses' },
]
const ADVANCED_TABS: { key: TabKey; label: string }[] = [
  { key: 'evaluation', label: 'Évaluation' },
  { key: 'relations', label: 'Entités & Relations' },
  { key: 'chunks', label: 'Chunks' },
]
const TABS = [...PRIMARY_TABS, ...ADVANCED_TABS]
const VALID_TABS = new Set(TABS.map((tab) => tab.key))
const ADVANCED_KEYS = new Set(ADVANCED_TABS.map((tab) => tab.key))
// Paramètres (chunking, embedding, visibilité, partages) est owner-only côté backend - un
// visiteur d'une collection publique/partagée ne le voit pas du tout, il n'y a rien qu'il
// puisse y faire.
const visiblePrimaryTabs = computed(() => PRIMARY_TABS.filter((tab) => tab.key !== 'settings' || props.collection.isOwner))

const showAdvancedMenu = ref(false)
const advancedWrapper = ref<HTMLElement | null>(null)
const isAdvancedTabActive = computed(() => ADVANCED_KEYS.has(activeTab.value))
const activeAdvancedLabel = computed(() => ADVANCED_TABS.find((tab) => tab.key === activeTab.value)?.label)

function handleOutsideClick(event: MouseEvent) {
  if (showAdvancedMenu.value && !advancedWrapper.value?.contains(event.target as Node)) {
    showAdvancedMenu.value = false
  }
}
onMounted(() => document.addEventListener('click', handleOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick))

// Resolve the initial tab from the URL (:tab param), falling back to the owner/default logic.
function resolveInitialTab(): TabKey {
  const urlTab = route.params.tab as string | undefined
  if (urlTab && VALID_TABS.has(urlTab as TabKey)) {
    // A non-owner can never land on "settings" - it's not in their visible tabs.
    if (urlTab === 'settings' && !props.collection.isOwner) return 'documents'
    return urlTab as TabKey
  }
  return props.collection.isOwner ? 'settings' : 'documents'
}

const activeTab = ref<TabKey>(resolveInitialTab())

// Tant que le nom et les paramètres n'ont pas été confirmés, on reste
// coincé sur l'onglet Paramètres - y compris si on y revient plus tard
// (changement de collection active, navigation directe par URL). Ne
// s'applique qu'à l'owner (voir isCollectionReady).
watch(
  () => [props.collection.id, isReady.value],
  () => {
    if (!isReady.value) activeTab.value = 'settings'
    else if (activeTab.value === 'settings' && !props.collection.isOwner) activeTab.value = 'documents'
  },
  { immediate: true },
)

// A direct link to /collections/:id/documents/:documentId (see DocumentDetailModal's own
// navigation) must land on the Documents tab even if something else was last selected.
watch(
  () => props.activeDocumentId,
  (id) => {
    if (id) activeTab.value = 'documents'
  },
  { immediate: true },
)

// When the active tab changes, load its data lazily (only the first time) and
// update the URL so the tab is shareable and survives back/forward navigation.
watch(
  activeTab,
  (tab) => {
    loadTabData(props.collection.id, tab)
    const target = `/collections/${props.collection.id}/${tab}`
    if (route.path !== target) router.replace(target)
  },
  { immediate: true },
)

// Sync from URL on back/forward navigation (route.params.tab changes without
// selectTab being called).
watch(
  () => route.params.tab,
  (tab) => {
    if (typeof tab === 'string' && VALID_TABS.has(tab as TabKey)) {
      if (tab === 'settings' && !props.collection.isOwner) return
      if (tab !== activeTab.value) activeTab.value = tab as TabKey
    }
  },
)

function selectTab(key: TabKey) {
  if (key !== 'settings' && !isReady.value) return
  activeTab.value = key
  showAdvancedMenu.value = false
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

const showDeleteModal = ref(false)

function confirmDelete() {
  showDeleteModal.value = false
  deleteCollection(props.collection.id)
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
          v-if="collection.isOwner && isEditingMeta"
          class="collection-detail__name"
          :value="collection.name"
          aria-label="Nom de la collection"
          @change="updateName(collection.id, ($event.target as HTMLInputElement).value)"
        />
        <h2 v-else class="collection-detail__name collection-detail__name--readonly">{{ collection.name }}</h2>
        <span
          class="collection-detail__visibility-badge"
          :class="`collection-detail__visibility-badge--${collection.isOwner ? 'owner' : collection.visibility === 'public' ? 'public' : 'shared'}`"
        >
          {{ collection.isOwner ? (collection.visibility === 'public' ? 'Publique' : 'Privée') : collection.visibility === 'public' ? 'Publique' : 'Partagée avec vous' }}
        </span>
        <button
          v-if="collection.isOwner && isReady"
          type="button"
          class="collection-detail__details-toggle"
          :class="{ 'collection-detail__details-toggle--active': isEditingMeta }"
          :title="isEditingMeta ? 'Terminer la modification' : 'Modifier le nom, la description et les tags'"
          @click="toggleEditMeta"
        >
          <svg v-if="!isEditingMeta" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M16.86 4.49a2.06 2.06 0 1 1 2.92 2.91L7.5 19.68l-4 1 1-4L16.86 4.49Z"
            />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
          </svg>
          <span class="fr-sr-only">{{ isEditingMeta ? 'Terminer la modification' : 'Modifier' }}</span>
        </button>
        <button
          type="button"
          class="collection-detail__details-toggle"
          :aria-expanded="showDetails"
          aria-controls="collection-detail-meta-card"
          :title="showDetails ? 'Masquer la description et les tags' : 'Afficher la description et les tags'"
          @click="showDetails = !showDetails"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            aria-hidden="true"
            :class="{ 'collection-detail__details-toggle-icon--open': showDetails }"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" />
          </svg>
          <span class="fr-sr-only">{{ showDetails ? 'Masquer les détails' : 'Afficher les détails' }}</span>
        </button>
        <button
          v-if="collection.isOwner"
          type="button"
          class="collection-detail__delete"
          @click="showDeleteModal = true"
        >
          Supprimer
        </button>
      </div>

      <div v-if="showDetails" id="collection-detail-meta-card" class="collection-detail__meta-card">
        <div class="collection-detail__meta-card-section">
          <span class="collection-detail__meta-card-label">
            Description
            <button
              v-if="collection.descriptionMeta"
              type="button"
              class="collection-detail__info"
              :title="formatStamp(collection.descriptionMeta)"
              :aria-label="formatStamp(collection.descriptionMeta)"
            >
              ⓘ
            </button>
          </span>
          <textarea
            v-if="collection.isOwner && isEditingMeta"
            class="collection-detail__description"
            :value="collection.description"
            placeholder="Décrivez cette collection…"
            rows="2"
            aria-label="Description de la collection"
            @change="updateDescription(collection.id, ($event.target as HTMLTextAreaElement).value)"
          />
          <p v-else-if="collection.description" class="collection-detail__description collection-detail__description--readonly">
            {{ collection.description }}
          </p>
          <p v-else class="collection-detail__description collection-detail__description--empty">Aucune description.</p>
        </div>

        <div class="collection-detail__meta-card-section">
          <span class="collection-detail__meta-card-label">
            Tags
            <button
              v-if="collection.tags.length && collection.tagsMeta"
              type="button"
              class="collection-detail__info"
              :title="formatStamp(collection.tagsMeta)"
              :aria-label="formatStamp(collection.tagsMeta)"
            >
              ⓘ
            </button>
          </span>
          <div class="collection-detail__tags">
            <span v-for="tag in collection.tags" :key="tag" class="collection-detail__tag">
              {{ tag }}
              <button
                v-if="collection.isOwner && isEditingMeta"
                type="button"
                :aria-label="`Retirer le tag ${tag}`"
                @click="removeTag(tag)"
              >
                ✕
              </button>
            </span>
            <input
              v-if="collection.isOwner && isEditingMeta"
              v-model="tagDraft"
              type="text"
              class="collection-detail__tag-input"
              placeholder="+ tag"
              aria-label="Ajouter un tag"
              @keydown.enter.prevent="addTag"
              @blur="addTag"
            />
            <span v-if="!collection.tags.length && !(collection.isOwner && isEditingMeta)" class="collection-detail__description--empty">
              Aucun tag.
            </span>
          </div>
        </div>
      </div>

      <nav class="collection-detail__tabs" aria-label="Sections de la collection">
        <button
          v-for="tab in visiblePrimaryTabs"
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

        <div ref="advancedWrapper" class="collection-detail__advanced">
          <button
            type="button"
            class="collection-detail__tab"
            :class="{ 'collection-detail__tab--active': isAdvancedTabActive }"
            :disabled="!isReady"
            :title="!isReady ? 'Nommez la collection et enregistrez ses paramètres d\'abord' : undefined"
            :aria-expanded="showAdvancedMenu"
            aria-haspopup="true"
            @click="showAdvancedMenu = !showAdvancedMenu"
          >
            {{ isAdvancedTabActive ? activeAdvancedLabel : 'Avancé' }}
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" />
            </svg>
          </button>

          <div v-if="showAdvancedMenu" class="collection-detail__advanced-menu" role="menu">
            <button
              v-for="tab in ADVANCED_TABS"
              :key="tab.key"
              type="button"
              role="menuitem"
              class="collection-detail__advanced-item"
              :class="{ 'collection-detail__advanced-item--active': activeTab === tab.key }"
              @click="selectTab(tab.key)"
            >
              {{ tab.label }}
            </button>
          </div>
        </div>
      </nav>

      <p v-if="!isReady" class="collection-detail__gate-hint">
        Donnez un nom à cette collection et enregistrez ses paramètres de découpage et de modèle d'embedding
        avant d'ajouter des documents.
      </p>

      <div class="collection-detail__panel">
        <Transition name="collection-tab" mode="out-in">
          <CollectionDocumentsTab
            v-if="activeTab === 'documents'"
            key="documents"
            :collection="collection"
            :active-document-id="activeDocumentId"
          />
          <CollectionQaTab v-else-if="activeTab === 'qa'" key="qa" :collection="collection" />
          <CollectionEvaluationTab v-else-if="activeTab === 'evaluation'" key="evaluation" :collection="collection" />
          <CollectionRelationsTab v-else-if="activeTab === 'relations'" key="relations" :collection="collection" />
          <CollectionChunksTab v-else-if="activeTab === 'chunks'" key="chunks" :collection="collection" />
          <CollectionSettingsTab v-else key="settings" :collection="collection" />
        </Transition>
      </div>
    </div>

    <ConfirmDeleteModal
      v-if="showDeleteModal"
      title="Supprimer cette collection ?"
      :warning="`Cette action est irréversible : tous les documents, questions/réponses, entités et chunks de « ${collection.name} » seront définitivement supprimés, y compris les fichiers et captures d'écran stockés.`"
      :confirm-text="collection.name"
      @confirm="confirmDelete"
      @cancel="showDeleteModal = false"
    />
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
  position: sticky;
  top: 0;
  z-index: 6;
  background: var(--background-default-grey);
  padding: 0.75rem 0;
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

.collection-detail__name--readonly {
  flex: 1;
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--text-default-grey);
  padding: 0.25rem 0;
}

.collection-detail__description--readonly {
  width: 100%;
  margin: 0;
  color: var(--text-mention-grey);
}

.collection-detail__description--empty {
  margin: 0;
  color: var(--text-disabled-grey);
  font-style: italic;
  font-size: 0.875rem;
}

.collection-detail__details-toggle {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 50%;
  background: var(--background-default-grey);
  color: var(--text-mention-grey);
  cursor: pointer;
}

.collection-detail__details-toggle:hover {
  color: var(--text-default-grey);
  border-color: var(--border-action-high-blue-france);
}

.collection-detail__details-toggle svg {
  transition: transform 0.15s ease;
}

.collection-detail__details-toggle svg.collection-detail__details-toggle-icon--open {
  transform: rotate(180deg);
}

.collection-detail__details-toggle--active {
  border-color: var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-detail__visibility-badge {
  flex-shrink: 0;
  padding: 0.25rem 0.625rem;
  border-radius: 1rem;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}

.collection-detail__visibility-badge--owner {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.collection-detail__visibility-badge--public {
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-detail__visibility-badge--shared {
  background: var(--background-alt-green-emeraude, var(--background-alt-grey));
  color: var(--text-default-success, var(--text-default-grey));
}

.collection-detail__description {
  width: 100%;
  margin: 0;
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

.collection-detail__meta-card {
  margin-top: 1rem;
  padding: 1rem 1.25rem;
  border-radius: 0.75rem;
  background: var(--background-alt-grey);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.collection-detail__meta-card-section {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.collection-detail__meta-card-label {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-mention-grey);
}

.collection-detail__info {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border: none;
  border-radius: 50%;
  padding: 0;
  background: transparent;
  color: var(--text-disabled-grey);
  font-size: 0.75rem;
  line-height: 1;
  cursor: help;
  text-transform: none;
  font-weight: 400;
  letter-spacing: normal;
}

.collection-detail__info:hover,
.collection-detail__info:focus-visible {
  color: var(--text-action-high-blue-france);
}

.collection-detail__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
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
  position: sticky;
  top: 3.25rem;
  z-index: 5;
  background: var(--background-default-grey);
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

.collection-detail__advanced {
  position: relative;
}

.collection-detail__advanced > .collection-detail__tab {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-right: 0;
}

.collection-detail__advanced-menu {
  position: absolute;
  top: calc(100% + 0.25rem);
  left: 0;
  z-index: 10;
  min-width: 11rem;
  display: flex;
  flex-direction: column;
  padding: 0.375rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.collection-detail__advanced-item {
  padding: 0.5rem 0.625rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  text-align: left;
  font-size: 0.875rem;
}

.collection-detail__advanced-item:hover {
  background: var(--background-alt-grey);
}

.collection-detail__advanced-item--active {
  color: var(--text-action-high-blue-france);
  font-weight: 700;
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

.collection-tab-enter-active,
.collection-tab-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.collection-tab-enter-from,
.collection-tab-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
