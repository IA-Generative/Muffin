<script setup lang="ts">
import { ref } from 'vue'
import type { RefreshSchedule } from '../utils/refreshSchedule'
import RefreshScheduleForm from './RefreshScheduleForm.vue'

defineProps<{
  url: string
}>()

const emit = defineEmits<{
  add: [schedule: RefreshSchedule | null]
  cancel: []
}>()

// Optional (#19): "Jamais" by default, and it can be changed later on the document's page.
const schedule = ref<RefreshSchedule | null>(null)
const valid = ref(true)

function submit() {
  if (valid.value) emit('add', schedule.value)
}
</script>

<template>
  <div class="url-modal-overlay" @click.self="emit('cancel')">
    <form class="url-modal" role="dialog" aria-modal="true" aria-labelledby="url-modal-title" @submit.prevent="submit">
      <h2 id="url-modal-title" class="url-modal__title">Ajouter une URL</h2>
      <p class="url-modal__url">{{ url }}</p>
      <p class="url-modal__hint">
        Une page web est indexée telle quelle ; un fichier (PDF, Word, tableur, image…) est téléchargé et traité comme
        un fichier déposé. La mise à jour automatique est facultative et reste modifiable sur la fiche du document.
      </p>

      <RefreshScheduleForm v-model="schedule" v-model:valid="valid" :initial="null" id-prefix="add-url" />

      <div class="url-modal__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
        <button type="submit" class="fr-btn" :disabled="!valid">Ajouter</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.url-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.url-modal {
  width: 100%;
  max-width: 36rem;
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

.url-modal__title {
  margin: 0;
  font-size: 1.125rem;
}

.url-modal__url {
  margin: 0;
  font-size: 0.875rem;
  word-break: break-all;
}

.url-modal__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.url-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>
