<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'

interface FilingSuggestionCandidate {
  collectionId: string
  collectionName: string
  collectionDescription: string
  score: number
}

// Structurally compatible with both ConversationFile (chat chip) and FilingCandidate (review
// page) - this modal only ever needs these fields from either shape, see ChatWindow.vue and
// FilingReviewView.vue.
interface FilingSubject {
  name: string
  suggestedCollectionId?: string | null
  filingCandidates: FilingSuggestionCandidate[]
}

const props = defineProps<{
  file: FilingSubject
}>()

const emit = defineEmits<{
  close: []
  decide: [action: 'accept' | 'choose_other' | 'dismiss', targetCollectionId?: string]
}>()

const { collections, createCollection } = useCollections()

const choosingOther = ref(false)
const search = ref('')

const filteredCollections = computed(() =>
  collections.value.filter((collection) => collection.name.toLowerCase().includes(search.value.trim().toLowerCase())),
)

// Below this, none of the candidates are convincing enough to lead with - still shown (a rough
// match beats none), but paired with the "create a new collection" shortcut instead of implying
// confidence there isn't. Same rough cut used by the review page's own scorePercent formatting.
const CONFIDENT_SCORE = 0.5
const bestScore = computed(() => props.file.filingCandidates[0]?.score ?? 0)

function scorePercent(score: number): string {
  return `${Math.round(score * 100)}%`
}

function pickCandidate(candidate: FilingSuggestionCandidate) {
  const action = candidate.collectionId === props.file.suggestedCollectionId ? 'accept' : 'choose_other'
  emit('decide', action, candidate.collectionId)
}

function decide(action: 'choose_other' | 'dismiss', targetCollectionId?: string) {
  emit('decide', action, targetCollectionId)
}

// Pre-fills a new collection's name from the file's own name (§122 follow-up) - the user still
// finishes setting it up normally (description, chunking, embedding) on the collection page this
// opens, same as the plain "+ Nouvelle collection" flow.
function createCollectionForFile() {
  const suggestedName = props.file.name.replace(/\.[^.]+$/, '')
  createCollection(suggestedName)
}
</script>

<template>
  <div class="filing-modal-overlay" @click.self="emit('close')">
    <div class="filing-modal" role="dialog" aria-modal="true" aria-labelledby="filing-modal-title">
      <header class="filing-modal__header">
        <h2 id="filing-modal-title" class="filing-modal__title">Ranger « {{ props.file.name }} »</h2>
        <button type="button" class="filing-modal__close" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>

      <div class="filing-modal__body">
        <template v-if="!choosingOther">
          <template v-if="props.file.filingCandidates.length > 0">
            <p>Collections qui pourraient correspondre :</p>
            <ul class="filing-modal__candidates">
              <li v-for="candidate in props.file.filingCandidates" :key="candidate.collectionId">
                <button type="button" class="filing-modal__candidate" @click="pickCandidate(candidate)">
                  <span class="filing-modal__candidate-header">
                    <span class="filing-modal__candidate-name">{{ candidate.collectionName }}</span>
                    <span class="filing-modal__candidate-score">{{ scorePercent(candidate.score) }}</span>
                  </span>
                  <span v-if="candidate.collectionDescription" class="filing-modal__candidate-description">
                    {{ candidate.collectionDescription }}
                  </span>
                </button>
              </li>
            </ul>
            <p v-if="bestScore < CONFIDENT_SCORE" class="filing-modal__hint">
              Aucune de ces suggestions n'est très convaincante -
              <button type="button" class="filing-modal__link" @click="createCollectionForFile">
                créer une nouvelle collection
              </button>
              pour ce fichier ?
            </p>
          </template>
          <template v-else>
            <p>Je n'ai pas trouvé de collection correspondante.</p>
            <button type="button" class="filing-modal__link" @click="createCollectionForFile">
              Créer une nouvelle collection pour ce fichier
            </button>
          </template>

          <div class="filing-modal__actions">
            <button type="button" class="fr-btn fr-btn--secondary" @click="choosingOther = true">
              Choisir une autre collection
            </button>
            <button type="button" class="fr-btn fr-btn--tertiary" @click="decide('dismiss')">Ne rien faire</button>
          </div>
        </template>

        <template v-else>
          <input
            v-model="search"
            type="text"
            class="filing-modal__search"
            placeholder="Rechercher une collection…"
            autofocus
          />
          <ul class="filing-modal__list">
            <li v-if="filteredCollections.length === 0" class="filing-modal__empty">Aucune collection trouvée.</li>
            <li v-for="collection in filteredCollections" :key="collection.id">
              <button type="button" class="filing-modal__row" @click="decide('choose_other', collection.id)">
                {{ collection.name }}
              </button>
            </li>
          </ul>
          <button type="button" class="fr-btn fr-btn--tertiary" @click="choosingOther = false">Retour</button>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filing-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.filing-modal {
  width: 100%;
  max-width: 28rem;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  box-sizing: border-box;
  overflow: hidden;
}

.filing-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem 0;
}

.filing-modal__title {
  margin: 0;
  font-size: 1.0625rem;
}

.filing-modal__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.filing-modal__body {
  padding: 1rem 1.5rem 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.filing-modal__candidates {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  max-height: 16rem;
  overflow-y: auto;
}

.filing-modal__candidate {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-family: inherit;
}

.filing-modal__candidate:hover {
  background: var(--background-alt-grey-hover);
}

.filing-modal__candidate-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
}

.filing-modal__candidate-score {
  flex-shrink: 0;
  color: var(--text-mention-grey);
  font-weight: 400;
  font-size: 0.75rem;
}

.filing-modal__candidate-description {
  color: var(--text-mention-grey);
  font-size: 0.75rem;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.filing-modal__hint {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.filing-modal__link {
  border: none;
  background: transparent;
  color: var(--text-action-high-blue-france);
  cursor: pointer;
  padding: 0;
  font: inherit;
  text-decoration: underline;
}

.filing-modal__actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.filing-modal__search {
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.filing-modal__search:focus {
  outline: none;
  border-color: var(--border-action-high-blue-france);
}

.filing-modal__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  overflow-y: auto;
  max-height: 16rem;
}

.filing-modal__empty {
  padding: 0.5rem 0.625rem;
  color: var(--text-disabled-grey);
  font-size: 0.8125rem;
}

.filing-modal__row {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
}

.filing-modal__row:hover {
  background: var(--background-alt-grey-hover);
}
</style>
