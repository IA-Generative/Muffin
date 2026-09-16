<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useModels } from '../composables/useModels'

const { models, selectedModel, isLoading, error, selectModel } = useModels()

const showMenu = ref(false)
const wrapper = ref<HTMLElement>()

function handleOutsideClick(event: MouseEvent) {
  if (showMenu.value && !wrapper.value?.contains(event.target as Node)) {
    showMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', handleOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick))

function pick(id: string) {
  selectModel(id)
  showMenu.value = false
}
</script>

<template>
  <div ref="wrapper" class="model-selector">
    <button
      type="button"
      class="model-selector__trigger"
      :disabled="isLoading || (!error && models.length === 0)"
      @click="showMenu = !showMenu"
    >
      <span>{{ isLoading ? 'Chargement…' : (error ?? selectedModel?.id ?? 'Aucun modèle') }}</span>
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path fill="currentColor" d="M7 10l5 5 5-5H7z" />
      </svg>
    </button>

    <ul v-if="showMenu" class="model-selector__menu" role="menu">
      <li v-for="model in models" :key="model.id">
        <button
          type="button"
          class="model-selector__item"
          :class="{ 'model-selector__item--active': model.id === selectedModel?.id }"
          role="menuitem"
          @click="pick(model.id)"
        >
          {{ model.id }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.model-selector {
  position: relative;
}

.model-selector__trigger {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  border-radius: 1rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.8125rem;
  font-family: inherit;
}

.model-selector__trigger:hover {
  background: var(--background-alt-grey-hover);
}

.model-selector__trigger:disabled {
  cursor: not-allowed;
  color: var(--text-disabled-grey);
}

.model-selector__menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin: 0.375rem 0 0;
  padding: 0.25rem;
  list-style: none;
  max-height: 20rem;
  overflow-y: auto;
  min-width: 12rem;
  background: var(--background-default-grey);
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 10;
}

.model-selector__item {
  display: block;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-selector__item:hover {
  background: var(--background-alt-grey-hover);
}

.model-selector__item--active {
  background: var(--background-alt-blue-france);
  font-weight: 600;
}
</style>
