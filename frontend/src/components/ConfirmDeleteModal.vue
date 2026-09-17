<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  title: string
  warning: string
  confirmText: string
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const typed = ref('')
const isMatch = () => typed.value === props.confirmText

function submit() {
  if (isMatch()) emit('confirm')
}
</script>

<template>
  <div class="confirm-delete-overlay" @click.self="emit('cancel')">
    <div class="confirm-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-delete-title">
      <h2 id="confirm-delete-title">{{ title }}</h2>
      <p class="confirm-delete-modal__warning">{{ warning }}</p>

      <label for="confirm-delete-input">
        Tapez <strong>{{ confirmText }}</strong> pour confirmer
      </label>
      <input
        id="confirm-delete-input"
        v-model="typed"
        type="text"
        autocomplete="off"
        :placeholder="confirmText"
        @keydown.enter="submit"
      />

      <div class="confirm-delete-modal__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
        <button type="button" class="fr-btn fr-btn--danger" :disabled="!isMatch()" @click="submit">
          Supprimer définitivement
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.confirm-delete-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.confirm-delete-modal {
  width: 100%;
  max-width: 26rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.confirm-delete-modal h2 {
  margin: 0 0 0.5rem;
  font-size: 1.125rem;
}

.confirm-delete-modal__warning {
  margin: 0 0 1.25rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.confirm-delete-modal label {
  display: block;
  font-size: 0.875rem;
  margin-bottom: 0.375rem;
}

.confirm-delete-modal input {
  width: 100%;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  box-sizing: border-box;
}

.confirm-delete-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1.5rem;
}

.fr-btn--danger {
  background-color: var(--background-action-high-error);
  color: var(--text-inverted-error);
}

.fr-btn--danger:disabled {
  background-color: var(--background-disabled-grey);
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}
</style>
