<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import type { CreationProposal } from '../types/chat'

const props = defineProps<{
  proposal: CreationProposal
  // The run that wrote the document: the proposal is stored with it, and so is the user's verdict.
  runId: string
}>()

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const { reloadDocuments } = useCollections()

// Starts from what the backend stored, then follows what the user does here.
const status = ref(props.proposal.status)
const documentId = ref(props.proposal.documentId)
const busy = ref(false)
const error = ref<string | null>(null)
const showFull = ref(false)

const html = computed(() => DOMPurify.sanitize(marked.parse(props.proposal.content, { async: false })))

const HEADLINE: Record<CreationProposal['status'], string> = {
  pending: 'Ce document n’est pas encore créé : relisez-le, puis créez-le ou refusez-le.',
  created: 'Document créé : il est en cours d’indexation dans la collection.',
  refused: 'Proposition refusée : rien n’a été créé.',
}

async function decide(action: 'validate' | 'refuse') {
  busy.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/runs/${props.runId}/creation/${action}`, {
      method: 'POST',
      credentials: 'include',
    })
    if (response.status === 403 || response.status === 404) {
      error.value = 'Vous ne pouvez plus créer de document dans cette collection.'
      return
    }
    if (response.status === 409) {
      error.value = 'Ce document a déjà été créé ou refusé : rechargez la conversation.'
      return
    }
    if (!response.ok) {
      error.value = `L’opération a échoué (${response.status}).`
      return
    }
    if (action === 'refuse') {
      status.value = 'refused'
      return
    }
    documentId.value = (await response.json()).id
    status.value = 'created'
    // The collection's document list may already be loaded: show the new document in it.
    await reloadDocuments(props.proposal.collectionId)
  } catch {
    error.value = 'Le serveur est inaccessible.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="creation" :class="`creation--${status}`" :aria-label="`Document proposé : ${proposal.name}`">
    <header class="creation__header">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
      </svg>
      <span class="creation__label">Nouveau document</span>
    </header>
    <p class="creation__name">{{ proposal.name }}.md</p>
    <p class="creation__where">Dans la collection « {{ proposal.collectionName }} »</p>

    <div class="creation__preview" :class="{ 'creation__preview--full': showFull }">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="creation__markdown" v-html="html" />
    </div>
    <button type="button" class="creation__toggle" @click="showFull = !showFull">
      {{ showFull ? 'Réduire l’aperçu' : 'Voir tout le document' }}
    </button>

    <p class="creation__status" role="status">{{ HEADLINE[status] }}</p>
    <p v-if="error" class="creation__error" role="alert">{{ error }}</p>

    <div v-if="status === 'pending'" class="creation__actions">
      <button type="button" class="fr-btn fr-btn--sm" :disabled="busy" @click="decide('validate')">
        Créer le document
      </button>
      <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" :disabled="busy" @click="decide('refuse')">
        Refuser
      </button>
    </div>
    <router-link
      v-else-if="status === 'created' && documentId"
      class="fr-btn fr-btn--secondary fr-btn--sm"
      :to="`/collections/${proposal.collectionId}/documents/${documentId}`"
    >
      Ouvrir le document
    </router-link>
  </section>
</template>

<style scoped>
.creation {
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

.creation--created {
  border-left-color: var(--border-plain-success);
}

.creation--refused {
  border-left-color: var(--border-default-grey);
}

.creation__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--text-mention-grey);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.creation__name {
  margin: 0.375rem 0 0.125rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.creation__where {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.creation__preview {
  max-height: 12rem;
  overflow: hidden;
  padding: 0.5rem 0.875rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
}

.creation__preview--full {
  max-height: 28rem;
  overflow-y: auto;
}

.creation__markdown {
  font-size: 0.875rem;
}

.creation__markdown :deep(h1) {
  font-size: 1.125rem;
}

.creation__markdown :deep(h2),
.creation__markdown :deep(h3) {
  font-size: 1rem;
}

.creation__toggle {
  margin: 0.25rem 0 0.5rem;
  padding: 0;
  border: none;
  background: none;
  color: var(--text-action-high-blue-france);
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
  text-decoration: underline;
}

.creation__status {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
}

.creation__error {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}

.creation__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
