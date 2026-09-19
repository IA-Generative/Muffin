<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useCollections } from '../composables/useCollections'

const selected = defineModel<string[]>({ required: true })
// Off by default (§ security: never search the web unless explicitly asked - see backend
// RunCreate.web_search_enabled) - stays on across messages once toggled, same as `selected`,
// until turned back off or the page reloads (owned by the parent, see ChatWindow.vue).
const webSearchEnabled = defineModel<boolean>('webSearchEnabled', { default: false })

const { collections } = useCollections()

// "Outils" menu section: one-off toggles alongside the collection picker, grouped here so a
// second tool later is just another entry, not a new top-level composer button.
const hasActiveTool = computed(() => webSearchEnabled.value)

const showActions = ref(false)
const showModal = ref(false)
const search = ref('')
const wrapper = ref<HTMLElement>()

function handleOutsideClick(event: MouseEvent) {
  if (showActions.value && !wrapper.value?.contains(event.target as Node)) {
    showActions.value = false
  }
}

onMounted(() => document.addEventListener('click', handleOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick))

function openCollectionsModal() {
  showActions.value = false
  search.value = ''
  showModal.value = true
}

function toggle(id: string) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((existing) => existing !== id)
    : [...selected.value, id]
}

const filteredCollections = computed(() =>
  collections.value.filter((collection) => collection.name.toLowerCase().includes(search.value.trim().toLowerCase())),
)
</script>

<template>
  <div ref="wrapper" class="collection-picker">
    <button
      type="button"
      class="collection-picker__trigger"
      :class="{ 'collection-picker__trigger--active': selected.length > 0 || hasActiveTool }"
      :aria-label="selected.length > 0 ? `${selected.length} collection(s) attachée(s)` : 'Actions'"
      @click="showActions = !showActions"
    >
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
        <path fill="currentColor" d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />
      </svg>
      <span v-if="selected.length > 0" class="collection-picker__badge">{{ selected.length }}</span>
      <span v-else-if="hasActiveTool" class="collection-picker__badge collection-picker__badge--dot" aria-hidden="true" />
    </button>

    <div v-if="showActions" class="collection-picker__menu" role="menu">
      <ul class="collection-picker__section">
        <li>
          <button type="button" class="collection-picker__item" role="menuitem" @click="openCollectionsModal">
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              <path
                fill="currentColor"
                d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"
              />
            </svg>
            <span>Collections</span>
          </button>
        </li>
      </ul>

      <p class="collection-picker__section-label">Outils</p>
      <ul class="collection-picker__section">
        <li>
          <button
            type="button"
            class="collection-picker__item"
            role="menuitemcheckbox"
            :aria-checked="webSearchEnabled"
            @click="webSearchEnabled = !webSearchEnabled"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
              <path
                fill="currentColor"
                d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm6.93 6h-3.1a15.9 15.9 0 0 0-1.3-4.02A8.02 8.02 0 0 1 18.93 8ZM12 4.06c.8 1.2 1.4 2.5 1.77 3.94H10.23c.37-1.44.97-2.74 1.77-3.94ZM4.26 14a8.14 8.14 0 0 1 0-4h3.55a16.4 16.4 0 0 0 0 4H4.26Zm.81 2h3.1c.3 1.44.72 2.8 1.3 4.02A8.02 8.02 0 0 1 5.07 16Zm3.1-8H5.07a8.02 8.02 0 0 1 4.4-4.02A15.9 15.9 0 0 0 8.17 8ZM12 19.94c-.8-1.2-1.4-2.5-1.77-3.94h3.54c-.37 1.44-.97 2.74-1.77 3.94ZM14.08 14H9.92a14.4 14.4 0 0 1 0-4h4.16a14.4 14.4 0 0 1 0 4Zm.15 5.98c.58-1.22 1-2.58 1.3-4.02h3.1a8.02 8.02 0 0 1-4.4 4.02ZM15.9 14a16.4 16.4 0 0 0 0-4h3.55a8.14 8.14 0 0 1 0 4H15.9Z"
              />
            </svg>
            <span>Recherche web</span>
            <svg
              v-if="webSearchEnabled"
              class="collection-picker__item-check"
              viewBox="0 0 24 24"
              width="14"
              height="14"
              aria-hidden="true"
            >
              <path fill="currentColor" d="M9 16.2l-3.5-3.5L4 14.2l5 5 11-11-1.5-1.5z" />
            </svg>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="showModal" class="collection-picker-modal-overlay" @click.self="showModal = false">
      <div
        class="collection-picker-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="collection-picker-modal-title"
      >
        <header class="collection-picker-modal__header">
          <h2 id="collection-picker-modal-title" class="collection-picker-modal__title">Attacher des collections</h2>
          <button type="button" class="collection-picker-modal__close" aria-label="Fermer" @click="showModal = false">
            ✕
          </button>
        </header>

        <div class="collection-picker-modal__body">
          <input
            v-model="search"
            type="text"
            class="collection-picker-modal__search"
            placeholder="Rechercher une collection…"
            autofocus
          />

          <ul class="collection-picker-modal__list">
            <li v-if="filteredCollections.length === 0" class="collection-picker-modal__empty">
              Aucune collection trouvée.
            </li>
            <li v-for="collection in filteredCollections" :key="collection.id">
              <button
                type="button"
                class="collection-picker-modal__row"
                :class="{ 'collection-picker-modal__row--active': selected.includes(collection.id) }"
                role="menuitemcheckbox"
                :aria-checked="selected.includes(collection.id)"
                @click="toggle(collection.id)"
              >
                <span class="collection-picker-modal__check" aria-hidden="true">
                  <svg v-if="selected.includes(collection.id)" viewBox="0 0 24 24" width="14" height="14">
                    <path fill="currentColor" d="M9 16.2l-3.5-3.5L4 14.2l5 5 11-11-1.5-1.5z" />
                  </svg>
                </span>
                <span class="collection-picker-modal__label">{{ collection.name }}</span>
              </button>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.collection-picker {
  position: relative;
  flex-shrink: 0;
}

.collection-picker__trigger {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  border: 1px solid var(--border-default-grey);
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
}

.collection-picker__trigger:hover {
  background: var(--background-alt-grey-hover);
}

.collection-picker__trigger--active {
  border-color: var(--border-action-high-blue-france);
  color: var(--text-action-high-blue-france);
}

.collection-picker__badge {
  position: absolute;
  top: -0.25rem;
  right: -0.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 1.1rem;
  height: 1.1rem;
  padding: 0 0.25rem;
  border-radius: 999px;
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
  font-size: 0.625rem;
  font-weight: 600;
}

.collection-picker__badge--dot {
  min-width: 0.5rem;
  width: 0.5rem;
  height: 0.5rem;
  padding: 0;
}

.collection-picker__menu {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin: 0 0 0.375rem;
  padding: 0.25rem;
  min-width: 12rem;
  background: var(--background-default-grey);
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 10;
}

.collection-picker__section {
  list-style: none;
  margin: 0;
  padding: 0;
}

.collection-picker__section-label {
  margin: 0.375rem 0.625rem 0.125rem;
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--text-mention-grey);
}

.collection-picker__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.8125rem;
  font-family: inherit;
}

.collection-picker__item-check {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-action-high-blue-france);
}

.collection-picker__item:hover {
  background: var(--background-alt-grey-hover);
}

.collection-picker-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.collection-picker-modal {
  width: 100%;
  max-width: 26rem;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.collection-picker-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.collection-picker-modal__title {
  margin: 0;
  font-size: 1.0625rem;
}

.collection-picker-modal__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.collection-picker-modal__body {
  padding: 1rem 1.5rem 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.collection-picker-modal__search {
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.collection-picker-modal__search:focus {
  outline: none;
  border-color: var(--border-action-high-blue-france);
}

.collection-picker-modal__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  overflow-y: auto;
}

.collection-picker-modal__empty {
  padding: 0.5rem 0.625rem;
  color: var(--text-disabled-grey);
  font-size: 0.8125rem;
}

.collection-picker-modal__row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
}

.collection-picker-modal__row:hover {
  background: var(--background-alt-grey-hover);
}

.collection-picker-modal__row--active {
  background: var(--background-alt-blue-france);
}

.collection-picker-modal__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  color: var(--text-action-high-blue-france);
}

.collection-picker-modal__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
