<script setup lang="ts">
// Le choix de l'assistant du chat (#514), à côté du modèle : un assistant se choisit comme un modèle, en un clic.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAssistants } from '../composables/useAssistants'
import { useAssistantSearch } from '../composables/useAssistantSearch'

const router = useRouter()
const { assistants, selectedAssistant, select, refreshAssistants } = useAssistants()

const { query, results, active, loading } = useAssistantSearch(computed(() => assistants.value))

const showMenu = ref(false)
const wrapper = ref<HTMLElement>()

function handleOutsideClick(event: MouseEvent) {
  if (showMenu.value && !wrapper.value?.contains(event.target as Node)) showMenu.value = false
}

onMounted(() => {
  document.addEventListener('click', handleOutsideClick)
  refreshAssistants()
})
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick))

function pick(id: string | null) {
  select(id)
  showMenu.value = false
  query.value = ''
}

function manage() {
  showMenu.value = false
  router.push('/assistants')
}
</script>

<template>
  <div ref="wrapper" class="assistant-selector">
    <button
      type="button"
      class="assistant-selector__trigger"
      aria-haspopup="menu"
      :aria-expanded="showMenu"
      @click="showMenu = !showMenu"
    >
      <span aria-hidden="true">{{ selectedAssistant?.icon || '✨' }}</span>
      <span>{{ selectedAssistant?.name ?? 'Sans assistant' }}</span>
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path fill="currentColor" d="M7 10l5 5 5-5H7z" />
      </svg>
    </button>

    <ul v-if="showMenu" class="assistant-selector__menu" role="menu">
      <li v-if="assistants.length > 3" class="assistant-selector__search">
        <input
          v-model="query"
          type="search"
          class="assistant-selector__search-input"
          placeholder="Rechercher un assistant…"
          aria-label="Rechercher un assistant par son nom ou sa description"
          autocomplete="off"
        />
        <span v-if="active" class="assistant-selector__status" role="status" aria-live="polite">
          {{ loading ? 'Recherche…' : results.length ? `${results.length} résultat${results.length > 1 ? 's' : ''}` : 'Aucun résultat' }}
        </span>
      </li>
      <li v-if="!active">
        <button
          type="button"
          class="assistant-selector__item"
          :class="{ 'assistant-selector__item--active': !selectedAssistant }"
          role="menuitem"
          @click="pick(null)"
        >
          Sans assistant
        </button>
      </li>
      <li v-for="assistant in results" :key="assistant.id">
        <button
          type="button"
          class="assistant-selector__item"
          :class="{ 'assistant-selector__item--active': assistant.id === selectedAssistant?.id }"
          role="menuitem"
          @click="pick(assistant.id)"
        >
          <span aria-hidden="true">{{ assistant.icon || '✨' }}</span> {{ assistant.name }}
          <span v-if="!assistant.isOwner" class="assistant-selector__shared">partagé</span>
        </button>
      </li>
      <li class="assistant-selector__footer">
        <button type="button" class="assistant-selector__item" role="menuitem" @click="manage">Gérer les assistants…</button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.assistant-selector {
  position: relative;
}

.assistant-selector__trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.875rem;
  cursor: pointer;
}

.assistant-selector__menu {
  position: absolute;
  z-index: 20;
  top: calc(100% + 0.25rem);
  left: 0;
  min-width: 15rem;
  max-height: 22rem;
  overflow-y: auto;
  margin: 0;
  padding: 0.25rem;
  list-style: none;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
  box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
}

.assistant-selector__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.625rem;
  border: 0;
  border-radius: 0.25rem;
  background: transparent;
  color: var(--text-default-grey);
  font-size: 0.875rem;
  text-align: left;
  cursor: pointer;
}

.assistant-selector__item:hover,
.assistant-selector__item--active {
  background: var(--background-contrast-grey);
}

.assistant-selector__shared {
  margin-left: auto;
  font-size: 0.6875rem;
  color: var(--text-mention-grey);
}

.assistant-selector__search {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.25rem;
}

.assistant-selector__search-input {
  width: 100%;
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.875rem;
}

.assistant-selector__status {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.assistant-selector__footer {
  margin-top: 0.25rem;
  padding-top: 0.25rem;
  border-top: 1px solid var(--border-default-grey);
}
</style>
