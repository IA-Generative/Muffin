<script setup lang="ts">
import { useTheme } from '../composables/useTheme'

defineEmits<{
  close: []
}>()

const { mode } = useTheme()

const options: { value: 'light' | 'dark' | 'system'; label: string }[] = [
  { value: 'light', label: 'Clair' },
  { value: 'dark', label: 'Sombre' },
  { value: 'system', label: 'Système' },
]
</script>

<template>
  <div class="settings-overlay" @click.self="$emit('close')">
    <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="settings-modal__header">
        <h2 id="settings-title">Paramètres</h2>
        <button type="button" class="settings-modal__close" aria-label="Fermer" @click="$emit('close')">
          ✕
        </button>
      </div>

      <fieldset class="settings-modal__field">
        <legend>Thème</legend>
        <div class="settings-modal__options">
          <button
            v-for="option in options"
            :key="option.value"
            type="button"
            class="settings-modal__option"
            :class="{ 'settings-modal__option--active': mode === option.value }"
            @click="mode = option.value"
          >
            {{ option.label }}
          </button>
        </div>
      </fieldset>
    </div>
  </div>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.settings-modal {
  width: 100%;
  max-width: 24rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.settings-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.settings-modal__header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.settings-modal__close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-mention-grey);
}

.settings-modal__field {
  border: none;
  padding: 0;
  margin: 1.5rem 0 0;
}

.settings-modal__field legend {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
  margin-bottom: 0.5rem;
  padding: 0;
}

.settings-modal__options {
  display: flex;
  gap: 0.5rem;
}

.settings-modal__option {
  flex: 1;
  padding: 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
}

.settings-modal__option:hover {
  background: var(--background-alt-grey-hover);
}

.settings-modal__option--active {
  border-color: var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  font-weight: 700;
}
</style>
