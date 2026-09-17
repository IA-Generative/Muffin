<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useEmbeddingModels } from '../composables/useEmbeddingModels'
import type { ChunkingSettings, Collection } from '../types/collection'

const props = defineProps<{
  collection: Collection
}>()

const {
  updateChunkingSettings,
  updateEmbeddingModel,
  reindexCollection,
  updateInstructionField,
  markSettingsSaved,
} = useCollections()
const { models: embeddingModels, isLoading: isLoadingEmbeddingModels, error: embeddingModelsError } =
  useEmbeddingModels()

const chunkingForm = reactive<ChunkingSettings>({ ...props.collection.chunkingSettings })
const chunkingInstructions = ref(props.collection.instructions.chunking)
const embeddingModelDraft = ref(props.collection.embeddingModel)
const qaInstructions = ref(props.collection.instructions.qa)
const extractionInstructions = ref(props.collection.instructions.extraction)
const taggingInstructions = ref(props.collection.instructions.tagging)

watch(
  () => props.collection.id,
  () => {
    Object.assign(chunkingForm, props.collection.chunkingSettings)
    chunkingInstructions.value = props.collection.instructions.chunking
    embeddingModelDraft.value = props.collection.embeddingModel
    qaInstructions.value = props.collection.instructions.qa
    extractionInstructions.value = props.collection.instructions.extraction
    taggingInstructions.value = props.collection.instructions.tagging
  },
)

// Chaque section se sauvegarde séparément et demande sa propre confirmation :
// ce n'est pas juste un champ de formulaire, ça affecte la façon dont les
// documents déjà indexés sont interprétés.
function saveChunking() {
  if (!confirm('Confirmer la modification des paramètres de découpage ? Cela peut nécessiter une réindexation.')) {
    return
  }
  updateChunkingSettings(props.collection.id, { ...chunkingForm })
  updateInstructionField(props.collection.id, 'chunking', chunkingInstructions.value)
  markSettingsSaved(props.collection.id)
}

function saveEmbeddingModel() {
  if (
    !confirm(
      "Confirmer le changement de modèle d'embedding ? Les documents déjà indexés devront être réindexés.",
    )
  ) {
    return
  }
  updateEmbeddingModel(props.collection.id, embeddingModelDraft.value)
  markSettingsSaved(props.collection.id)
}

const STRATEGY_HINT: Record<ChunkingSettings['strategy'], string> = {
  paragraph: 'Découpe le texte à chaque paragraphe. Simple et robuste pour des documents bien structurés.',
  fixed: 'Découpe en blocs de taille fixe, sans tenir compte de la structure du texte.',
  semantic:
    'Regroupe les phrases par similarité de sens avant de découper : la taille des chunks en résulte, elle ne se règle pas.',
  llm: "Un LLM lit le document et décide lui-même où découper, guidé par les instructions ci-dessous. La taille en résulte, elle ne se règle pas.",
}

// Le chevauchement (tokens répétés d'un chunk à l'autre) n'a de sens que
// quand le découpage suit une grille fixe ; sémantique et LLM choisissent
// déjà leurs frontières pour préserver le sens, un chevauchement forcé n'y
// ajoute rien.
const showChunkSize = () => chunkingForm.strategy === 'paragraph' || chunkingForm.strategy === 'fixed'
</script>

<template>
  <div class="settings-tab">
    <form class="settings-tab__section" @submit.prevent="saveChunking">
      <h3 class="settings-tab__title">Découpage (chunking)</h3>

      <div class="settings-tab__field">
        <label for="chunk-strategy">Stratégie de découpage</label>
        <select id="chunk-strategy" v-model="chunkingForm.strategy" class="fr-select">
          <option value="paragraph">Par paragraphe</option>
          <option value="fixed">Taille fixe</option>
          <option value="semantic">Sémantique</option>
          <option value="llm">Par LLM</option>
        </select>
        <p class="settings-tab__hint">{{ STRATEGY_HINT[chunkingForm.strategy] }}</p>
      </div>

      <div v-if="showChunkSize()" class="settings-tab__field">
        <label for="chunk-size">Taille des chunks (tokens)</label>
        <input id="chunk-size" v-model.number="chunkingForm.chunkSize" type="number" min="64" max="4096" step="64" />
      </div>

      <div v-if="showChunkSize()" class="settings-tab__field">
        <label for="chunk-overlap">Chevauchement (tokens)</label>
        <input id="chunk-overlap" v-model.number="chunkingForm.chunkOverlap" type="number" min="0" max="512" step="8" />
        <p class="settings-tab__hint">
          Nombre de tokens répétés entre deux chunks consécutifs, pour ne pas perdre le contexte à la coupure.
        </p>
      </div>

      <div class="settings-tab__field">
        <label for="instructions-chunking">
          Instructions de découpage{{ chunkingForm.strategy === 'llm' ? ' (utilisées par le LLM)' : '' }}
        </label>
        <textarea
          id="instructions-chunking"
          v-model="chunkingInstructions"
          rows="2"
          placeholder="Ex. Ne jamais couper une clause juridique en deux chunks."
        />
      </div>

      <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveEmbeddingModel">
      <h3 class="settings-tab__title">Modèle d'embedding</h3>

      <div class="settings-tab__field">
        <label for="embedding-model">Modèle</label>
        <select
          id="embedding-model"
          v-model="embeddingModelDraft"
          class="fr-select"
          :disabled="isLoadingEmbeddingModels"
        >
          <option
            v-if="embeddingModelDraft && !embeddingModels.some((model) => model.id === embeddingModelDraft)"
            :value="embeddingModelDraft"
          >
            {{ embeddingModelDraft }}
          </option>
          <option v-for="model in embeddingModels" :key="model.id" :value="model.id">{{ model.id }}</option>
        </select>
        <p v-if="embeddingModelsError" class="settings-tab__hint">{{ embeddingModelsError }}</p>
        <p class="settings-tab__hint">
          Changer de modèle rend les vecteurs déjà calculés incompatibles : les documents doivent être réindexés.
        </p>
      </div>

      <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>

      <div v-if="collection.reindexRequired" class="settings-tab__reindex">
        <span>Le modèle d'embedding a changé : les documents ne sont plus à jour.</span>
        <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="reindexCollection(collection.id)">
          Réindexer maintenant
        </button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="updateInstructionField(collection.id, 'qa', qaInstructions)">
      <h3 class="settings-tab__title">Génération de questions-réponses</h3>
      <div class="settings-tab__field">
        <label for="instructions-qa">Instructions</label>
        <textarea
          id="instructions-qa"
          v-model="qaInstructions"
          rows="2"
          placeholder="Ex. Formuler des questions courtes, au tutoiement, orientées agents publics."
        />
      </div>
      <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
    </form>

    <form
      class="settings-tab__section"
      @submit.prevent="updateInstructionField(collection.id, 'extraction', extractionInstructions)"
    >
      <h3 class="settings-tab__title">Extraction d'entités et relations</h3>
      <div class="settings-tab__field">
        <label for="instructions-extraction">Instructions</label>
        <textarea
          id="instructions-extraction"
          v-model="extractionInstructions"
          rows="2"
          placeholder="Ex. Prioriser les entités de type organisation et ignorer les dates relatives."
        />
      </div>
      <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
    </form>

    <form
      class="settings-tab__section"
      @submit.prevent="updateInstructionField(collection.id, 'tagging', taggingInstructions)"
    >
      <h3 class="settings-tab__title">Tags automatiques</h3>
      <div class="settings-tab__field">
        <label for="instructions-tagging">Instructions</label>
        <textarea
          id="instructions-tagging"
          v-model="taggingInstructions"
          rows="2"
          placeholder="Ex. Toujours ajouter un tag par direction métier citée dans le document."
        />
      </div>
      <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
    </form>
  </div>
</template>

<style scoped>
.settings-tab {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  max-width: 24rem;
}

.settings-tab__section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.settings-tab__section:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.settings-tab__title {
  margin: 0;
  font-size: 1rem;
}

.settings-tab__field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.settings-tab__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.settings-tab__field input,
.settings-tab__field textarea {
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  resize: vertical;
}

.settings-tab__hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.settings-tab__section button.fr-btn {
  align-self: flex-start;
}

.settings-tab__reindex {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-orange-terre-battue, var(--background-alt-grey));
  font-size: 0.8125rem;
}
</style>
