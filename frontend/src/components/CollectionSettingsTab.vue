<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useEmbeddingModels } from '../composables/useEmbeddingModels'
import { useModels } from '../composables/useModels'
import type { ChunkingSettings, Collection, GenerationModels, PipelineWindows } from '../types/collection'

const props = defineProps<{
  collection: Collection
}>()

const {
  updateChunkingSettings,
  updateEmbeddingModel,
  updateGenerationModel,
  updatePipelineWindows,
  reindexCollection,
  updateInstructionField,
  markSettingsSaved,
} = useCollections()
const { models: embeddingModels, isLoading: isLoadingEmbeddingModels, error: embeddingModelsError } =
  useEmbeddingModels()
const { models: chatModels, isLoading: isLoadingChatModels, error: chatModelsError } = useModels()

const chunkingForm = reactive<ChunkingSettings>({ ...props.collection.chunkingSettings })
const chunkingInstructions = ref(props.collection.instructions.chunking)
const embeddingModelDraft = ref(props.collection.embeddingModel)
const qaInstructions = ref(props.collection.instructions.qa)
const extractionInstructions = ref(props.collection.instructions.extraction)
const taggingInstructions = ref(props.collection.instructions.tagging)
const summaryInstructions = ref(props.collection.instructions.summary)

// One shared object for every sliding-window param: they all live in the
// same pipeline_windows blob on the backend anyway.
const windowsForm = reactive<PipelineWindows>({ ...props.collection.pipelineWindows })

// Falls back to the first available chat model until the user has picked
// one explicitly for this step.
function modelDraftFor(field: keyof GenerationModels) {
  return ref(props.collection.generationModels[field] ?? chatModels.value[0]?.id ?? '')
}
const chunkingModelDraft = modelDraftFor('chunking')
const qaModelDraft = modelDraftFor('qa')
const extractionModelDraft = modelDraftFor('extraction')
const taggingModelDraft = modelDraftFor('tagging')
const summaryModelDraft = modelDraftFor('summary')

const noModelsAvailable = computed(() => !isLoadingChatModels.value && chatModels.value.length === 0)

watch(
  () => props.collection.id,
  () => {
    Object.assign(chunkingForm, props.collection.chunkingSettings)
    Object.assign(windowsForm, props.collection.pipelineWindows)
    chunkingInstructions.value = props.collection.instructions.chunking
    embeddingModelDraft.value = props.collection.embeddingModel
    qaInstructions.value = props.collection.instructions.qa
    extractionInstructions.value = props.collection.instructions.extraction
    taggingInstructions.value = props.collection.instructions.tagging
    summaryInstructions.value = props.collection.instructions.summary
    chunkingModelDraft.value = props.collection.generationModels.chunking ?? chatModels.value[0]?.id ?? ''
    qaModelDraft.value = props.collection.generationModels.qa ?? chatModels.value[0]?.id ?? ''
    extractionModelDraft.value = props.collection.generationModels.extraction ?? chatModels.value[0]?.id ?? ''
    taggingModelDraft.value = props.collection.generationModels.tagging ?? chatModels.value[0]?.id ?? ''
    summaryModelDraft.value = props.collection.generationModels.summary ?? chatModels.value[0]?.id ?? ''
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
  if (chunkingForm.strategy === 'llm' && chunkingModelDraft.value) {
    updateGenerationModel(props.collection.id, 'chunking', chunkingModelDraft.value)
  }
  if (chunkingForm.strategy === 'semantic') {
    updatePipelineWindows(props.collection.id, {
      chunkingWindowPages: windowsForm.chunkingWindowPages,
      chunkingSlidePages: windowsForm.chunkingSlidePages,
    })
  }
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

function saveQa() {
  updateInstructionField(props.collection.id, 'qa', qaInstructions.value)
  if (qaModelDraft.value) updateGenerationModel(props.collection.id, 'qa', qaModelDraft.value)
  updatePipelineWindows(props.collection.id, {
    qaWindowPages: windowsForm.qaWindowPages,
    qaSlidePages: windowsForm.qaSlidePages,
    qaQuestionsPerWindow: windowsForm.qaQuestionsPerWindow,
    collectionQaCount: windowsForm.collectionQaCount,
  })
}

function saveExtraction() {
  updateInstructionField(props.collection.id, 'extraction', extractionInstructions.value)
  if (extractionModelDraft.value) updateGenerationModel(props.collection.id, 'extraction', extractionModelDraft.value)
  updatePipelineWindows(props.collection.id, {
    extractionWindowPages: windowsForm.extractionWindowPages,
    extractionSlidePages: windowsForm.extractionSlidePages,
  })
}

function saveTagging() {
  updateInstructionField(props.collection.id, 'tagging', taggingInstructions.value)
  if (taggingModelDraft.value) updateGenerationModel(props.collection.id, 'tagging', taggingModelDraft.value)
}

function saveSummary() {
  updateInstructionField(props.collection.id, 'summary', summaryInstructions.value)
  if (summaryModelDraft.value) updateGenerationModel(props.collection.id, 'summary', summaryModelDraft.value)
  updatePipelineWindows(props.collection.id, { summaryPagesPerMap: windowsForm.summaryPagesPerMap })
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
    <form class="settings-tab__section" @submit.prevent="saveSummary">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M9 12h6m-6 4h4m-7 4h10a2 2 0 0 0 2-2V8.5L13.5 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2Z"
            />
          </svg>
        </span>
        <h3 class="settings-tab__title">Résumé</h3>
      </div>

      <div class="settings-tab__body">
        <div class="settings-tab__field">
          <label for="instructions-summary">Instructions</label>
          <textarea
            id="instructions-summary"
            v-model="summaryInstructions"
            rows="2"
            placeholder="Ex. Rédiger un résumé factuel de 5 lignes maximum, sans jugement."
          />
        </div>
        <div class="settings-tab__field">
          <label for="summary-pages-per-map">Pages par lot (map)</label>
          <input
            id="summary-pages-per-map"
            v-model.number="windowsForm.summaryPagesPerMap"
            type="number"
            min="1"
            max="50"
          />
          <p class="settings-tab__hint">
            Le résumé se fait en map-reduce : chaque lot de N pages est résumé séparément (map), puis ces résumés
            partiels sont combinés (reduce).
          </p>
        </div>
        <div class="settings-tab__field">
          <label for="model-summary">Modèle</label>
          <select id="model-summary" v-model="summaryModelDraft" class="fr-select" :disabled="isLoadingChatModels">
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <p v-if="chatModelsError" class="settings-tab__hint">{{ chatModelsError }}</p>
          <p v-else-if="noModelsAvailable" class="settings-tab__hint">Aucun modèle disponible.</p>
        </div>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveChunking">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M3.75 3.75h6v6h-6v-6Zm10.5 0h6v6h-6v-6Zm-10.5 10.5h6v6h-6v-6Zm10.5 0h6v6h-6v-6Z"
            />
          </svg>
        </span>
        <h3 class="settings-tab__title">Découpage (chunking)</h3>
      </div>

      <div class="settings-tab__body">
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
          <input id="chunk-size" v-model.number="chunkingForm.chunkSize" type="number" min="64" max="4096" />
        </div>

        <div v-if="showChunkSize()" class="settings-tab__field">
          <label for="chunk-overlap">Chevauchement (tokens)</label>
          <input id="chunk-overlap" v-model.number="chunkingForm.chunkOverlap" type="number" min="0" max="512" />
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

        <div v-if="chunkingForm.strategy === 'llm'" class="settings-tab__field">
          <label for="model-chunking">Modèle utilisé pour le découpage</label>
          <select id="model-chunking" v-model="chunkingModelDraft" class="fr-select" :disabled="isLoadingChatModels">
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <p v-if="chatModelsError" class="settings-tab__hint">{{ chatModelsError }}</p>
          <p v-else-if="noModelsAvailable" class="settings-tab__hint">Aucun modèle disponible.</p>
        </div>

        <template v-if="chunkingForm.strategy === 'semantic'">
          <div class="settings-tab__field">
            <label for="chunking-window-pages">Fenêtre de pages</label>
            <input
              id="chunking-window-pages"
              v-model.number="windowsForm.chunkingWindowPages"
              type="number"
              min="1"
              max="20"
            />
          </div>
          <div class="settings-tab__field">
            <label for="chunking-slide-pages">Pas de la fenêtre glissante</label>
            <input
              id="chunking-slide-pages"
              v-model.number="windowsForm.chunkingSlidePages"
              type="number"
              min="1"
              max="20"
            />
            <p class="settings-tab__hint">
              La fenêtre avance de ce nombre de pages à chaque étape ; un pas plus petit que la fenêtre crée un
              chevauchement entre deux fenêtres consécutives.
            </p>
          </div>
        </template>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveEmbeddingModel">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="m21 7.5-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"
            />
          </svg>
        </span>
        <h3 class="settings-tab__title">Modèle d'embedding</h3>
      </div>

      <div class="settings-tab__body">
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

        <div v-if="collection.reindexRequired" class="settings-tab__reindex">
          <span>Le modèle d'embedding a changé : les documents ne sont plus à jour.</span>
          <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="reindexCollection(collection.id)">
            Réindexer maintenant
          </button>
        </div>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveQa">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M8.25 15.75a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.75 3.75 0 0 1 18.75 15.75h-1.5M8.25 15.75h7.5m-7.5 0-1.5 3.75m9-3.75 1.5 3.75"
            />
          </svg>
        </span>
        <h3 class="settings-tab__title">Questions-réponses</h3>
      </div>

      <div class="settings-tab__body">
        <div class="settings-tab__field">
          <label for="instructions-qa">Instructions</label>
          <textarea
            id="instructions-qa"
            v-model="qaInstructions"
            rows="2"
            placeholder="Ex. Formuler des questions courtes, au tutoiement, orientées agents publics."
          />
        </div>
        <div class="settings-tab__field">
          <label for="qa-window-pages">Fenêtre de pages (contexte)</label>
          <input id="qa-window-pages" v-model.number="windowsForm.qaWindowPages" type="number" min="1" max="20" />
          <p class="settings-tab__hint">Nombre de pages fournies en contexte pour générer des questions.</p>
        </div>
        <div class="settings-tab__field">
          <label for="qa-slide-pages">Pas de la fenêtre glissante</label>
          <input id="qa-slide-pages" v-model.number="windowsForm.qaSlidePages" type="number" min="1" max="20" />
        </div>
        <div class="settings-tab__field">
          <label for="qa-questions-per-window">Questions générées par fenêtre (k)</label>
          <input
            id="qa-questions-per-window"
            v-model.number="windowsForm.qaQuestionsPerWindow"
            type="number"
            min="1"
            max="20"
          />
        </div>
        <div class="settings-tab__field">
          <label for="model-qa">Modèle</label>
          <select id="model-qa" v-model="qaModelDraft" class="fr-select" :disabled="isLoadingChatModels">
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <p v-if="chatModelsError" class="settings-tab__hint">{{ chatModelsError }}</p>
          <p v-else-if="noModelsAvailable" class="settings-tab__hint">Aucun modèle disponible.</p>
        </div>
        <div class="settings-tab__field">
          <label for="collection-qa-count">QA générées pour la collection</label>
          <input
            id="collection-qa-count"
            v-model.number="windowsForm.collectionQaCount"
            type="number"
            min="1"
            max="20"
          />
          <p class="settings-tab__hint">
            Nombre de questions-réponses générées à partir de la description de la collection (pas liées à un
            document), à chaque fois que la description change.
          </p>
        </div>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveExtraction">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244"
            />
          </svg>
        </span>
        <h3 class="settings-tab__title">Extraction d'entités et relations</h3>
      </div>

      <div class="settings-tab__body">
        <div class="settings-tab__field">
          <label for="instructions-extraction">Instructions</label>
          <textarea
            id="instructions-extraction"
            v-model="extractionInstructions"
            rows="2"
            placeholder="Ex. Prioriser les entités de type organisation et ignorer les dates relatives."
          />
        </div>
        <div class="settings-tab__field">
          <label for="extraction-window-pages">Fenêtre de pages (contexte)</label>
          <input
            id="extraction-window-pages"
            v-model.number="windowsForm.extractionWindowPages"
            type="number"
            min="1"
            max="20"
          />
        </div>
        <div class="settings-tab__field">
          <label for="extraction-slide-pages">Pas de la fenêtre glissante</label>
          <input
            id="extraction-slide-pages"
            v-model.number="windowsForm.extractionSlidePages"
            type="number"
            min="1"
            max="20"
          />
        </div>
        <div class="settings-tab__field">
          <label for="model-extraction">Modèle</label>
          <select
            id="model-extraction"
            v-model="extractionModelDraft"
            class="fr-select"
            :disabled="isLoadingChatModels"
          >
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <p v-if="chatModelsError" class="settings-tab__hint">{{ chatModelsError }}</p>
          <p v-else-if="noModelsAvailable" class="settings-tab__hint">Aucun modèle disponible.</p>
        </div>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>

    <form class="settings-tab__section" @submit.prevent="saveTagging">
      <div class="settings-tab__header">
        <span class="settings-tab__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M9.568 3H5.25A2.25 2.25 0 0 0 3 5.25v4.318c0 .597.237 1.169.659 1.591l9.581 9.581c.699.699 1.83.699 2.53 0l7.409-7.409a1.789 1.789 0 0 0 0-2.53L13.16 3.66A2.25 2.25 0 0 0 11.568 3Z"
            />
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6Z" />
          </svg>
        </span>
        <h3 class="settings-tab__title">Tags automatiques</h3>
      </div>

      <div class="settings-tab__body">
        <div class="settings-tab__field">
          <label for="instructions-tagging">Instructions</label>
          <textarea
            id="instructions-tagging"
            v-model="taggingInstructions"
            rows="2"
            placeholder="Ex. Toujours ajouter un tag par direction métier citée dans le document."
          />
        </div>
        <div class="settings-tab__field">
          <label for="model-tagging">Modèle</label>
          <select id="model-tagging" v-model="taggingModelDraft" class="fr-select" :disabled="isLoadingChatModels">
            <option v-for="model in chatModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
          <p v-if="chatModelsError" class="settings-tab__hint">{{ chatModelsError }}</p>
          <p v-else-if="noModelsAvailable" class="settings-tab__hint">Aucun modèle disponible.</p>
        </div>
      </div>

      <div class="settings-tab__footer">
        <button type="submit" class="fr-btn fr-btn--sm">Enregistrer</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.settings-tab {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.25rem;
  max-width: 72rem;
}

/* Fixed height + internal scroll, not "grow with content": every card is
   the same size regardless of how many fields it has, and the tab itself
   stops growing tall - only a card's own body scrolls if it overflows. */
.settings-tab__section {
  display: flex;
  flex-direction: column;
  height: 26rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 1rem;
  background: var(--background-default-grey);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
  overflow: hidden;
}

.settings-tab__section:hover {
  border-color: var(--border-action-high-blue-france);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.settings-tab__header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.625rem;
  height: 3.75rem;
  padding: 0 1.25rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.settings-tab__icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
}

.settings-tab__title {
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-tab__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1.125rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.settings-tab__footer {
  flex-shrink: 0;
  padding: 0.875rem 1.25rem;
  border-top: 1px solid var(--border-default-grey);
}

.settings-tab__field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.settings-tab__field label {
  font-size: 0.8125rem;
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
