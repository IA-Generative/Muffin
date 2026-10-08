<script setup lang="ts">
import { computed } from 'vue'
import { useDraftSession } from '../composables/useDraftSession'
import type { DocumentDraft } from '../composables/useDocumentDraft'
import type { EditProposal } from '../types/chat'
import DraftReviewModal from './DraftReviewModal.vue'

const props = defineProps<{
  proposal: EditProposal
}>()

const { draft, loaded, busy, error, reviewing, validated, adjust, upload, insertImages, refuse, validate } =
  useDraftSession(
    computed(() => props.proposal.collectionId),
    computed(() => props.proposal.documentId),
    { openWhenReady: false },
  )

// The card follows the proposal's real state, read from the backend: the research agent's answer
// is a snapshot, but the user may have validated, refused or let it lapse since.
const state = computed<'loading' | 'pending' | 'ready' | 'declined' | 'failed' | 'validated' | 'gone'>(() => {
  const current: DocumentDraft | null = draft.value
  if (current) {
    if (current.status === 'pending') return 'pending'
    if (current.status === 'failed') return 'failed'
    return current.edited ? 'ready' : 'declined'
  }
  if (validated.value) return 'validated'
  return loaded.value ? 'gone' : 'loading'
})

const HEADLINE: Record<typeof state.value, string> = {
  loading: 'Chargement de la proposition…',
  pending: 'L’agent d’édition prépare la modification…',
  ready: 'La modification est prête à être relue.',
  declined: 'L’agent d’édition n’a rien modifié.',
  failed: 'La modification n’a pas abouti.',
  validated: 'Modification validée : le document est en cours de ré-indexation.',
  gone: 'Cette proposition n’est plus en attente (validée, refusée ou expirée).',
}

const canOpen = computed(() => !['loading', 'validated', 'gone'].includes(state.value))
</script>

<template>
  <section class="proposal" :class="`proposal--${state}`" :aria-label="`Modification proposée : ${proposal.documentName}`">
    <header class="proposal__header">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" />
      </svg>
      <span class="proposal__label">Modification d’un document</span>
    </header>
    <p class="proposal__document">{{ proposal.documentName }}</p>
    <p class="proposal__status" role="status">
      <span v-if="state === 'pending' || state === 'loading'" class="proposal__spinner" aria-hidden="true" />
      {{ HEADLINE[state] }}
    </p>
    <p v-if="state === 'failed' && draft?.error" class="proposal__error" role="alert">{{ draft.error }}</p>
    <p v-if="error && !reviewing" class="proposal__error" role="alert">{{ error }}</p>
    <div v-if="canOpen" class="proposal__actions">
      <button type="button" class="fr-btn fr-btn--sm" @click="reviewing = true">
        {{ state === 'ready' ? 'Examiner la modification' : 'Ouvrir' }}
      </button>
      <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" :disabled="busy" @click="refuse">
        Abandonner
      </button>
    </div>

    <DraftReviewModal
      v-if="draft && reviewing"
      :collection-id="proposal.collectionId"
      :document-id="proposal.documentId"
      :draft="draft"
      :busy="busy"
      :error="error"
      @close="reviewing = false"
      @adjust="adjust"
      @validate="validate"
      @refuse="refuse"
      @upload="upload"
      @insert-images="insertImages"
    />
  </section>
</template>

<style scoped>
.proposal {
  width: 100%;
  max-width: 34rem;
  box-sizing: border-box;
  margin-top: 0.75rem;
  padding: 0.875rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-left: 4px solid var(--border-action-high-blue-france);
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
}

.proposal--failed {
  border-left-color: var(--border-plain-error);
}

.proposal--validated {
  border-left-color: var(--border-plain-success);
}

.proposal--gone,
.proposal--declined {
  border-left-color: var(--border-default-grey);
}

.proposal__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-mention-grey);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.proposal__document {
  margin: 0.375rem 0 0.25rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.proposal__status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
}

.proposal__error {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.proposal__actions {
  display: flex;
  gap: 0.5rem;
}

.proposal__spinner {
  width: 0.875rem;
  height: 0.875rem;
  border: 2px solid var(--border-default-grey);
  border-top-color: var(--border-action-high-blue-france);
  border-radius: 50%;
  animation: proposal-spin 0.8s linear infinite;
}

@keyframes proposal-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .proposal__spinner {
    animation: none;
  }
}
</style>
