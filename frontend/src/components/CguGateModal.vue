<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'
import { useCgu } from '../composables/useCgu'
import { useCurrentUser } from '../composables/useCurrentUser'

// Mandatory, non-dismissible (§127) - mounted by App.vue whenever status.accepted is false, no
// close button, no click-outside-to-close. The only ways out are "J'accepte" or logging out.
const { status, error, acceptCgu } = useCgu()
const { logout } = useCurrentUser()

const submitting = ref(false)

const renderedContent = computed(() =>
  status.value?.content ? DOMPurify.sanitize(marked.parse(status.value.content, { async: false })) : '',
)

async function accept() {
  submitting.value = true
  await acceptCgu()
  submitting.value = false
}
</script>

<template>
  <div class="cgu-gate-overlay">
    <div class="cgu-gate" role="dialog" aria-modal="true" aria-labelledby="cgu-gate-title">
      <header class="cgu-gate__header">
        <h1 id="cgu-gate-title">
          {{ status?.isUpdate ? 'Les conditions générales d\'utilisation ont été mises à jour' : 'Conditions générales d\'utilisation' }}
        </h1>
        <p v-if="status?.isUpdate" class="cgu-gate__update-hint">
          Vous aviez déjà accepté une version précédente - merci de relire et d'accepter cette nouvelle version pour
          continuer à utiliser Muffin.
        </p>
        <p v-else class="cgu-gate__update-hint">
          Merci de lire et d'accepter les conditions générales d'utilisation pour utiliser Muffin.
        </p>
      </header>

      <div class="cgu-gate__content" v-html="renderedContent" />

      <p v-if="error" class="cgu-gate__error" role="alert">{{ error }}</p>

      <footer class="cgu-gate__actions">
        <button type="button" class="fr-btn fr-btn--secondary" @click="logout()">Refuser et se déconnecter</button>
        <button type="button" class="fr-btn" :disabled="submitting" @click="accept">J'accepte</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.cgu-gate-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1.5rem;
}

.cgu-gate {
  width: 100%;
  max-width: 40rem;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
  padding: 1.5rem 1.75rem;
}

.cgu-gate__header h1 {
  font-size: 1.25rem;
  margin: 0 0 0.5rem;
}

.cgu-gate__update-hint {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
  margin: 0 0 1rem;
}

.cgu-gate__content {
  overflow-y: auto;
  border-top: 1px solid var(--border-default-grey);
  border-bottom: 1px solid var(--border-default-grey);
  padding: 1rem 0;
  margin-bottom: 1rem;
}

.cgu-gate__content :deep(h1) {
  font-size: 1.125rem;
  margin: 0 0 0.75rem;
}

.cgu-gate__content :deep(h2) {
  font-size: 1rem;
  margin: 1.25rem 0 0.5rem;
}

.cgu-gate__content :deep(p),
.cgu-gate__content :deep(li) {
  font-size: 0.875rem;
  line-height: 1.5;
}

.cgu-gate__error {
  color: var(--text-default-error);
  font-size: 0.875rem;
  margin: 0 0 0.75rem;
}

.cgu-gate__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
</style>
