<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchEntityMentions, type EntityMention } from '../composables/useEntityMentions'
import SourceDocumentModal from './SourceDocumentModal.vue'

// The occurrences of an entity in the text (#352): each opens its page with the name highlighted and framed where
// it is, and one goes from one to the next - across the pages and the documents it is in.
const props = defineProps<{
  collectionId: string
  entityId: string
  entityName: string
  // Only the occurrences in this document (the document's own view of its entities).
  documentId?: string
}>()

const emit = defineEmits<{
  close: []
}>()

const mentions = ref<EntityMention[]>([])
const index = ref(0)
const loading = ref(true)
const failed = ref(false)

const current = computed(() => mentions.value[index.value])

onMounted(async () => {
  try {
    mentions.value = await fetchEntityMentions(props.collectionId, props.entityId, props.documentId)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <!-- Keyed by the occurrence: the modal loads its page when it is made, so another occurrence is another modal. -->
  <SourceDocumentModal
    v-if="current"
    :key="index"
    :collection-id="collectionId"
    :document-id="current.documentId"
    :document-name="current.documentName"
    :page-number="current.pageNumber"
    :excerpt="entityName"
    :start="current.start"
    :end="current.end"
    @close="emit('close')"
  >
    <template #extra>
      <nav class="entity-occurrences__nav" aria-label="Occurrences de l'entité">
        <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" :disabled="index === 0" @click="index--">
          Occurrence précédente
        </button>
        <span class="entity-occurrences__count" aria-live="polite">
          Occurrence {{ index + 1 }} sur {{ mentions.length }}
        </span>
        <button
          type="button"
          class="fr-btn fr-btn--tertiary fr-btn--sm"
          :disabled="index === mentions.length - 1"
          @click="index++"
        >
          Occurrence suivante
        </button>
      </nav>
    </template>
  </SourceDocumentModal>

  <div v-else class="entity-occurrences__overlay" @click.self="emit('close')">
    <div class="entity-occurrences__empty" role="dialog" aria-modal="true" :aria-label="entityName">
      <p v-if="loading">Chargement…</p>
      <p v-else-if="failed" role="alert">Impossible de charger les occurrences de « {{ entityName }} ».</p>
      <p v-else>« {{ entityName }} » n'est retrouvée nulle part dans le texte tel qu'il est écrit.</p>
      <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="emit('close')">Fermer</button>
    </div>
  </div>
</template>

<style scoped>
.entity-occurrences__nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.entity-occurrences__count {
  font-size: 0.875rem;
}

.entity-occurrences__overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.entity-occurrences__empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.5rem;
  max-width: 28rem;
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.875rem;
}

.entity-occurrences__empty p {
  margin: 0;
}
</style>
