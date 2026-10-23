<script setup lang="ts">
// La première configuration d'une collection, pas à pas : un profil, les modèles, puis un récapitulatif avec ce que
// ça coûte. Remplit le brouillon des réglages et l'enregistre d'un coup à la fin ; tout reste modifiable ensuite
// dans les paramètres.
import { computed, onMounted, ref } from 'vue'
import '../assets/settings-form.css'
import { useCollections } from '../composables/useCollections'
import { useEmbeddingModels } from '../composables/useEmbeddingModels'
import { useIndexingEstimate } from '../composables/useIndexingEstimate'
import type { Collection } from '../types/collection'
import { applyProfile, detectProfile, profileById, PROFILES, type Profile } from '../utils/collectionProfiles'
import { commonModel, setCommonModel, toPatch, validateSettings, type SettingsDraft } from '../utils/settingsDraft'
import { chunkingSummary, longDocsSummary } from '../utils/settingsSummary'
import ModelSelect from './ModelSelect.vue'
import ProfilePicker from './ProfilePicker.vue'
import SettingsField from './SettingsField.vue'

const props = defineProps<{
  collection: Collection
  draft: SettingsDraft
  // Les réglages enregistrés, pour ne demander que ce qui change.
  saved: SettingsDraft
}>()
const emit = defineEmits<{ done: [] }>()

const { saveCollectionSettings } = useCollections()
const { models: embeddingModels, isLoading: isLoadingEmbeddingModels, error: embeddingModelsError } = useEmbeddingModels()

const STEPS = [
  { title: 'Votre besoin', next: 'Les modèles' },
  { title: 'Les modèles', next: 'Récapitulatif' },
  { title: 'Récapitulatif', next: null },
] as const
const step = ref(0)
const saving = ref(false)
const saveError = ref<string | null>(null)

// Une collection neuve (aucun document, réglages par défaut) démarre sur le profil recommandé ; une collection qui a
// déjà des réglages ou des documents garde les siens : rien n'est remplacé sans que l'utilisateur le choisisse.
onMounted(() => {
  const untouched = props.collection.documentCount === 0 && detectProfile(props.draft) === 'precise'
  if (untouched) applyProfile(props.draft, PROFILES.find((profile) => profile.recommended) ?? profileById('balanced'))
})

const selectedProfile = computed(() => detectProfile(props.draft))
const profileLabel = computed(() =>
  selectedProfile.value ? profileById(selectedProfile.value).label : 'Personnalisé',
)
const errors = computed(() => validateSettings(props.draft))
const invalid = computed(() => Object.keys(errors.value).length > 0)

const estimate = useIndexingEstimate({
  collectionId: () => props.collection.id,
  longDocs: () => props.draft.longDocs,
  chunkingStrategy: () => props.draft.chunking.strategy,
  valid: () => !invalid.value,
})

const generationModel = computed({
  get: () => commonModel(props.draft.models) ?? '',
  set: (value: string) => setCommonModel(props.draft.models, value),
})
const modelsDiffer = computed(() => commonModel(props.draft.models) === null)

const needsName = computed(
  () => props.collection.name.trim() === '' || props.collection.name === 'Nouvelle collection',
)

function choose(profile: Profile) {
  applyProfile(props.draft, profile)
}

async function finish() {
  if (invalid.value) return
  saving.value = true
  saveError.value = await saveCollectionSettings(props.collection.id, toPatch(props.draft, props.saved))
  saving.value = false
  if (saveError.value === null) emit('done')
}
</script>

<template>
  <section class="wizard" aria-labelledby="wizard-title">
    <div class="fr-stepper">
      <h2 id="wizard-title" class="fr-stepper__title">
        <span class="fr-stepper__state">Étape {{ step + 1 }} sur {{ STEPS.length }}</span>
        {{ STEPS[step].title }}
      </h2>
      <div class="fr-stepper__steps" :data-fr-current-step="step + 1" :data-fr-steps="STEPS.length"></div>
      <p v-if="STEPS[step].next" class="fr-stepper__details">
        <span class="fr-text--bold">Étape suivante :</span> {{ STEPS[step].next }}
      </p>
    </div>

    <div v-if="step === 0" class="sf-stack">
      <p>
        Choisissez ce que vous privilégiez. Cela règle le découpage des documents et ce qui est lu des documents très
        longs ; vous pourrez tout ajuster ensuite dans les paramètres.
      </p>
      <ProfilePicker
        :selected="selectedProfile"
        :collection-id="collection.id"
        :long-docs="draft.longDocs"
        group-name="wizard-profile"
        @choose="choose"
      />
    </div>

    <div v-else-if="step === 1" class="sf-stack">
      <SettingsField
        id="wizard-embedding"
        label="Modèle d'embedding"
        hint="Il sert à retrouver les passages qui répondent à une question. Plus tard, en changer oblige à réindexer les documents."
        :error="embeddingModelsError ?? undefined"
      >
        <template #default="{ id, describedby }">
          <select
            :id="id"
            v-model="draft.embeddingModel"
            class="fr-select"
            :disabled="isLoadingEmbeddingModels"
            :aria-describedby="describedby"
          >
            <option
              v-if="draft.embeddingModel && !embeddingModels.some((model) => model.id === draft.embeddingModel)"
              :value="draft.embeddingModel"
            >
              {{ draft.embeddingModel }}
            </option>
            <option v-for="model in embeddingModels" :key="model.id" :value="model.id">{{ model.id }}</option>
          </select>
        </template>
      </SettingsField>

      <SettingsField
        id="wizard-generation"
        label="Modèle de génération"
        hint="Il écrit les résumés, les questions-réponses, les entités et les tags, et peut découper les documents. Un modèle différent par étape se choisit ensuite dans les réglages avancés."
      >
        <template #default="{ id, describedby }">
          <ModelSelect :id="id" v-model="generationModel" :describedby="describedby" :mixed="modelsDiffer" />
        </template>
      </SettingsField>
      <p v-if="modelsDiffer" class="sf-hint">Les étapes utilisent déjà des modèles différents ; en choisir un ici les remplace tous.</p>
    </div>

    <div v-else class="sf-stack">
      <dl class="wizard__recap">
        <dt>Profil</dt>
        <dd>{{ profileLabel }}</dd>
        <dt>Découpage</dt>
        <dd>{{ chunkingSummary(draft) }}</dd>
        <dt>Documents longs</dt>
        <dd>{{ longDocsSummary(draft) }}</dd>
        <dt>Modèle d'embedding</dt>
        <dd>{{ draft.embeddingModel }}</dd>
        <dt>Modèle de génération</dt>
        <dd>{{ generationModel || 'Modèle par défaut du serveur' }}</dd>
      </dl>

      <div class="sf-callout" aria-live="polite">
        <template v-if="estimate.state.draft">
          <p>
            Environ <strong>{{ estimate.state.draft.chat.total }} appels</strong> au modèle pour un document de
            {{ estimate.state.draft.pages }} pages<template
              v-if="estimate.state.full && estimate.state.full.chat.total !== estimate.state.draft.chat.total"
            >
              (au lieu de {{ estimate.state.full.chat.total }} en lisant tout)</template>.
          </p>
        </template>
        <p v-else-if="estimate.state.error" class="sf-error">{{ estimate.state.error }}</p>
        <p v-else class="sf-hint">Calcul de l'estimation…</p>
      </div>

      <p v-if="needsName" class="sf-callout sf-callout--warning">
        Pensez à donner un nom à la collection (en haut de la page) : il est nécessaire pour y ajouter des documents.
      </p>
      <p v-if="saveError" class="sf-error" role="alert">{{ saveError }}</p>
    </div>

    <div class="wizard__nav">
      <button v-if="step > 0" type="button" class="fr-btn fr-btn--secondary" @click="step--">Retour</button>
      <button v-if="step < STEPS.length - 1" type="button" class="fr-btn" @click="step++">Continuer</button>
      <button v-else type="button" class="fr-btn" :disabled="saving || invalid" @click="finish">
        {{ saving ? 'Enregistrement…' : 'Terminer la configuration' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.wizard {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 1rem;
  background: var(--background-default-grey);
}

.wizard :deep(.fr-stepper) {
  margin-bottom: 0;
}

.wizard__recap {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.5rem 1.5rem;
  margin: 0;
}

.wizard__recap dt {
  font-weight: 700;
}

.wizard__recap dd {
  margin: 0;
}

.wizard__nav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
