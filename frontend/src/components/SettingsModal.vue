<script setup lang="ts">
import { onMounted } from 'vue'
import { useNotifications } from '../composables/useNotifications'
import { useTheme } from '../composables/useTheme'

defineEmits<{
  close: []
}>()

const { mode } = useTheme()
const { preferences, preferencesError, loadPreferences, setPreference } = useNotifications()

onMounted(loadPreferences)

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

      <fieldset class="settings-modal__field">
        <legend>Me prévenir dans l’application</legend>
        <p v-if="preferencesError" class="settings-modal__error" role="alert">{{ preferencesError }}</p>
        <div v-for="preference in preferences" :key="preference.type" class="fr-checkbox-group settings-modal__preference">
          <input
            :id="`notification-${preference.type}`"
            type="checkbox"
            :checked="preference.app"
            :aria-describedby="`notification-${preference.type}-hint`"
            @change="setPreference(preference.type, ($event.target as HTMLInputElement).checked)"
          />
          <label class="fr-label" :for="`notification-${preference.type}`">
            {{ preference.label }}
            <span :id="`notification-${preference.type}-hint`" class="fr-hint-text">{{ preference.description }}</span>
          </label>
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
  max-width: 28rem;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.settings-modal__preference {
  margin-bottom: 0.75rem;
}

.settings-modal__error {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  color: var(--text-default-error);
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
