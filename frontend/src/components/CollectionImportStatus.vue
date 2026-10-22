<script setup lang="ts">
import { computed, ref } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useCollectionImports } from '../composables/useCollectionImports'
import type { CollectionImport } from '../composables/useCollectionImports'

const props = defineProps<{
  item: CollectionImport
}>()

const { openCollection } = useCollections()
const { reprocessFailed } = useCollectionImports()
const showSkipped = ref(false)

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count > 1 ? pluralForm : singular}`
}

const message = computed(() => {
  const item = props.item
  switch (item.status) {
    case 'queued':
      return `« ${item.archiveName} » sera importée avec votre message.`
    case 'uploading':
      return `Envoi de « ${item.archiveName} »…`
    case 'pending':
    case 'running':
      return `Import de « ${item.archiveName} » en cours…`
    case 'completed': {
      const summary = item.summary
      if (!summary) return `« ${item.archiveName} » importée.`
      return (
        `« ${item.rootCollectionName ?? item.archiveName} » créée : ` +
        `${plural(summary.collectionsCreated, 'sous-collection', 'sous-collections')}, ` +
        `${plural(summary.documentsCreated, 'document', 'documents')}.`
      )
    }
    default:
      return item.error ?? `L'import de « ${item.archiveName} » a échoué.`
  }
})

// The documents of a finished import that ended in error can be relaunched (#340): they wait for their turn
// in the import's window again. The answer says how many were.
const relaunched = ref<number | null>(null)
const relaunchFailed = ref(false)

async function relaunch() {
  relaunchFailed.value = false
  relaunched.value = await reprocessFailed(props.item.id)
  relaunchFailed.value = relaunched.value === null
}

const isError = computed(() => props.item.status === 'failed' || props.item.status === 'upload_failed')
const skipped = computed(() => props.item.summary?.skipped ?? [])
</script>

<template>
  <div class="import-status" :class="{ 'import-status--error': isError }" role="status">
    <p class="import-status__message">
      {{ message }}
      <button
        v-if="item.rootCollectionId && (item.status === 'completed' || item.status === 'failed')"
        type="button"
        class="import-status__link"
        @click="openCollection(item.rootCollectionId)"
      >
        Ouvrir
      </button>
    </p>
    <button
      v-if="item.status === 'completed' || item.status === 'failed'"
      type="button"
      class="import-status__link"
      @click="relaunch"
    >
      Relancer les documents en erreur
    </button>
    <p v-if="relaunched !== null" class="import-status__result">
      {{ relaunched > 1 ? `${relaunched} documents relancés.` : `${relaunched} document relancé.` }}
    </p>
    <p v-if="relaunchFailed" class="import-status__result" role="alert">Impossible de relancer l'indexation.</p>
    <!-- Partial failures keep what was created (#223): the summary still says what was skipped. -->
    <template v-if="skipped.length">
      <button type="button" class="import-status__link" :aria-expanded="showSkipped" @click="showSkipped = !showSkipped">
        {{ plural(skipped.length, 'fichier ignoré', 'fichiers ignorés') }}
      </button>
      <ul v-if="showSkipped" class="import-status__skipped">
        <li v-for="entry in skipped" :key="entry.path">
          <span class="import-status__path">{{ entry.path }}</span> : {{ entry.reason }}
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.import-status {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
  padding: 0.625rem 0.875rem;
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
  font-size: 0.8125rem;
}

.import-status--error {
  color: var(--text-default-error);
}

.import-status__message {
  margin: 0;
}

.import-status__link {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-action-high-blue-france);
  font: inherit;
  text-decoration: underline;
  cursor: pointer;
}

.import-status__result {
  margin: 0;
  color: var(--text-mention-grey);
}

.import-status__skipped {
  margin: 0;
  padding-left: 1.25rem;
  color: var(--text-mention-grey);
}

.import-status__path {
  font-family: monospace;
}
</style>
