<script setup lang="ts">
import { computed, ref } from 'vue'

defineProps<{
  // Set by the parent when the backend refused the creation - the form stays open so nothing typed is lost.
  error: string | null
}>()

const emit = defineEmits<{
  create: [name: string, content: string]
  cancel: []
}>()

const name = ref('')
const content = ref('')

const canSubmit = computed(() => name.value.trim() !== '' && content.value.trim() !== '')

function submit() {
  if (canSubmit.value) emit('create', name.value.trim(), content.value)
}
</script>

<template>
  <div class="markdown-modal-overlay" @click.self="emit('cancel')">
    <form
      class="markdown-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="markdown-modal-title"
      @submit.prevent="submit"
    >
      <h2 id="markdown-modal-title" class="markdown-modal__title">Nouveau document Markdown</h2>
      <p class="markdown-modal__hint">
        Le document est indexé comme un fichier .md et pourra ensuite être remplacé par une nouvelle version, avec
        historique.
      </p>

      <label for="markdown-name">Nom du document</label>
      <input
        id="markdown-name"
        v-model="name"
        type="text"
        autocomplete="off"
        placeholder="Procédure d'accueil"
        maxlength="200"
      />

      <label for="markdown-content">Contenu (Markdown)</label>
      <textarea id="markdown-content" v-model="content" rows="14" placeholder="# Titre&#10;&#10;Votre texte…" />

      <p v-if="error" class="markdown-modal__error" role="alert">{{ error }}</p>

      <div class="markdown-modal__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
        <button type="submit" class="fr-btn" :disabled="!canSubmit">Créer le document</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.markdown-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.markdown-modal {
  width: 100%;
  max-width: 40rem;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
}

.markdown-modal__title {
  margin: 0;
  font-size: 1.125rem;
}

.markdown-modal__hint {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.markdown-modal label {
  font-size: 0.875rem;
  font-weight: 600;
  margin-top: 0.5rem;
}

.markdown-modal input,
.markdown-modal textarea {
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.markdown-modal textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875rem;
  resize: vertical;
}

.markdown-modal__error {
  margin: 0.5rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.markdown-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}
</style>
