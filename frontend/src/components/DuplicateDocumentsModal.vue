<script setup lang="ts">
import type { PendingDuplicate } from '../composables/useCollections'

defineProps<{
  // What the collection refused as already there - never empty while the modal is shown.
  duplicates: PendingDuplicate[]
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

function label(duplicate: PendingDuplicate): string {
  return duplicate.kind === 'file' ? duplicate.file.name : duplicate.url
}
</script>

<template>
  <div class="duplicate-modal-overlay" @click.self="emit('cancel')">
    <div class="duplicate-modal" role="dialog" aria-modal="true" aria-labelledby="duplicate-modal-title">
      <h2 id="duplicate-modal-title" class="duplicate-modal__title">
        {{ duplicates.length > 1 ? 'Ces documents sont déjà dans la collection' : 'Ce document est déjà dans la collection' }}
      </h2>
      <ul class="duplicate-modal__list">
        <li v-for="(duplicate, index) in duplicates" :key="index">
          <strong class="duplicate-modal__name">« {{ label(duplicate) }} »</strong>
          est identique à « {{ duplicate.existingName }} ».
        </li>
      </ul>
      <p class="duplicate-modal__hint">
        L'ajouter quand même crée un second document. Son traitement reprend les résultats du premier : il est
        rapide.
      </p>
      <div class="duplicate-modal__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Ne pas l'ajouter</button>
        <button type="button" class="fr-btn" @click="emit('confirm')">Ajouter quand même</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.duplicate-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.duplicate-modal {
  width: 100%;
  max-width: 32rem;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.5rem;
  box-sizing: border-box;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
}

.duplicate-modal__title {
  margin: 0;
  font-size: 1.125rem;
}

.duplicate-modal__list {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.875rem;
}

.duplicate-modal__name {
  word-break: break-all;
}

.duplicate-modal__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.duplicate-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>
