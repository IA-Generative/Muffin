<script lang="ts">
import type { SettingsDraft } from '../utils/settingsDraft'

// Un brouillon modifié survit au changement d'onglet : l'onglet est démonté, pas la collection.
const pendingDrafts = new Map<string, SettingsDraft>()
</script>

<script setup lang="ts">
// L'onglet Paramètres d'une collection. Une collection qui n'a jamais été configurée passe d'abord par l'assistant
// (profil, modèles, récapitulatif). Ensuite les réglages sont groupés par ce qu'ils font, repliés avec leur état en
// une ligne, les réglages techniques cachés dans « Réglages avancés », et enregistrés d'un seul bouton.
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import '../assets/settings-form.css'
import { useCollections } from '../composables/useCollections'
import { useEmbeddingModels } from '../composables/useEmbeddingModels'
import type { Collection } from '../types/collection'
import { applyProfile, detectProfile, profileById, type Profile } from '../utils/collectionProfiles'
import {
  assignDraft,
  changedSections,
  cloneDraft,
  commonModel,
  confirmations,
  draftFromCollection,
  SECTION_LABELS,
  setCommonModel,
  toPatch,
  validateSettings,
  type SettingsErrors,
  type SettingsSection as SectionKey,
} from '../utils/settingsDraft'
import { chunkingSummary, longDocsSummary, stepSummary } from '../utils/settingsSummary'
import CollectionAccessSettings from './CollectionAccessSettings.vue'
import CollectionSetupWizard from './CollectionSetupWizard.vue'
import LongDocumentsFields from './LongDocumentsFields.vue'
import ModelSelect from './ModelSelect.vue'
import ProfilePicker from './ProfilePicker.vue'
import SettingsField from './SettingsField.vue'
import SettingsSection from './SettingsSection.vue'

const props = defineProps<{ collection: Collection }>()

const {
  hasSavedSettings,
  saveCollectionSettings,
  reindexCollection,
  indexRebuilds,
  indexRebuildError,
  finalizeIndexRebuild,
  rollbackIndexRebuild,
} = useCollections()
const { models: embeddingModels, isLoading: isLoadingEmbeddingModels, error: embeddingModelsError } = useEmbeddingModels()

// -- le brouillon ------------------------------------------------------------------------------------------------

const saved = computed(() => draftFromCollection(props.collection))

const draft = reactive<SettingsDraft>(cloneDraft(saved.value))
function load(collectionId: string) {
  assignDraft(draft, pendingDrafts.get(collectionId) ?? saved.value)
  pendingDrafts.delete(collectionId)
}
load(props.collection.id)

watch(
  () => props.collection.id,
  (_, previous) => {
    if (previous && changed.value.length) pendingDrafts.set(previous, cloneDraft(draft))
    load(props.collection.id)
    configured.value = hasSavedSettings(props.collection.id)
    saveError.value = null
  },
)
// Les réglages enregistrés changent (enregistrement, réindexation…) : un brouillon intact les suit, un brouillon
// modifié garde ce qui a été saisi.
watch(saved, (now, before) => {
  if (!changedSections(draft, before).length) assignDraft(draft, now)
})
onBeforeUnmount(() => {
  if (changed.value.length) pendingDrafts.set(props.collection.id, cloneDraft(draft))
})

const changed = computed(() => changedSections(draft, saved.value))
const errors = computed<SettingsErrors>(() => validateSettings(draft))
const hasErrors = computed(() => Object.keys(errors.value).length > 0)

const SECTION_FIELDS: Record<SectionKey, (keyof SettingsErrors)[]> = {
  embedding: [],
  chunking: ['chunkSize', 'chunkOverlap', 'chunkingWindowPages', 'chunkingSlidePages'],
  summary: ['summaryPagesPerMap'],
  qa: ['qaWindowPages', 'qaSlidePages', 'qaQuestionsPerWindow', 'collectionQaCount'],
  extraction: ['extractionWindowPages', 'extractionSlidePages'],
  tagging: [],
  longDocs: [
    'samplingMinPages',
    'summaryPercent',
    'summaryHeadPercent',
    'summaryTailPercent',
    'summaryPageRanges',
    'qaMaxQuestions',
    'extractionPercent',
    'extractionMaxWindows',
  ],
}
const invalid = computed(
  () =>
    Object.fromEntries(
      (Object.keys(SECTION_FIELDS) as SectionKey[]).map((section) => [
        section,
        SECTION_FIELDS[section].some((field) => errors.value[field]),
      ]),
    ) as Record<SectionKey, boolean>,
)
const isChanged = (section: SectionKey) => changed.value.includes(section)

// -- première configuration ---------------------------------------------------------------------------------------

const configured = ref(hasSavedSettings(props.collection.id))

// -- profil, modèle commun ---------------------------------------------------------------------------------------

const selectedProfile = computed(() => detectProfile(draft))
const profileSummary = computed(() =>
  selectedProfile.value ? profileById(selectedProfile.value).label : 'Personnalisé (réglé à la main)',
)
function chooseProfile(profile: Profile) {
  applyProfile(draft, profile)
}

const generationModel = computed({
  get: () => commonModel(draft.models) ?? '',
  set: (value: string) => setCommonModel(draft.models, value),
})
const modelsDiffer = computed(() => commonModel(draft.models) === null)

// -- enregistrement ----------------------------------------------------------------------------------------------

const saving = ref(false)
const saveError = ref<string | null>(null)
const justSaved = ref(false)

async function save() {
  justSaved.value = false
  if (hasErrors.value || !changed.value.length) return
  const warnings = confirmations(draft, saved.value)
  if (warnings.length && !confirm(`${warnings.join('\n')}\n\nEnregistrer quand même ?`)) return
  saving.value = true
  saveError.value = await saveCollectionSettings(props.collection.id, toPatch(draft, saved.value))
  saving.value = false
  justSaved.value = saveError.value === null
}

function discard() {
  assignDraft(draft, saved.value)
  saveError.value = null
}

watch(
  () => changed.value.length,
  () => {
    justSaved.value = false
  },
)

const changedLabels = computed(() => changed.value.map((section) => SECTION_LABELS[section]).join(', '))
const invalidLabels = computed(() =>
  (Object.keys(invalid.value) as SectionKey[])
    .filter((section) => invalid.value[section])
    .map((section) => SECTION_LABELS[section])
    .join(', '),
)

// -- réindexation ------------------------------------------------------------------------------------------------

const indexRebuild = computed(() => indexRebuilds.value[props.collection.id] ?? null)

const STRATEGY_HINT = {
  llm: "Le modèle lit le document et décide lui-même où couper, guidé par vos consignes. Sans modèle disponible, le découpage se fait par paragraphe.",
  paragraph: 'Coupe le texte à chaque paragraphe. Simple et robuste pour des documents bien structurés.',
  fixed: 'Coupe en blocs de taille fixe, sans tenir compte de la structure du texte.',
  semantic: 'Regroupe les phrases par similarité de sens avant de couper : la taille des chunks en résulte, elle ne se règle pas.',
} as const
</script>

<template>
  <div class="settings-tab">
    <CollectionSetupWizard
      v-if="!configured"
      :collection="collection"
      :draft="draft"
      :saved="saved"
      @done="configured = true"
    />

    <template v-else>
      <p class="settings-tab__intro">
        Ouvrez une section pour la régler. Les réglages techniques sont dans « Réglages avancés » : les valeurs par
        défaut conviennent à la plupart des collections. Rien n'est appliqué avant d'avoir cliqué sur « Enregistrer ».
      </p>

      <section class="settings-tab__group" aria-labelledby="group-profile">
        <h3 id="group-profile" class="settings-tab__group-title">Profil</h3>
        <SettingsSection title="Rapide, équilibré ou précis ?" :summary="profileSummary">
          <ProfilePicker
            :selected="selectedProfile"
            :collection-id="collection.id"
            :long-docs="draft.longDocs"
            group-name="settings-profile"
            @choose="chooseProfile"
          />
        </SettingsSection>
      </section>

      <section class="settings-tab__group" aria-labelledby="group-read">
        <h3 id="group-read" class="settings-tab__group-title">Lire et retrouver les documents</h3>

        <SettingsSection
          title="Découpage"
          :summary="chunkingSummary(draft)"
          :changed="isChanged('chunking')"
          :invalid="invalid.chunking"
          :force-open="invalid.chunking"
        >
          <p class="sf-hint">
            Les documents sont découpés en passages (chunks) dans lesquels la recherche retrouve les réponses.
          </p>
          <SettingsField id="chunk-strategy" label="Comment couper les documents" :hint="STRATEGY_HINT[draft.chunking.strategy]">
            <template #default="{ id, describedby }">
              <select :id="id" v-model="draft.chunking.strategy" class="fr-select" :aria-describedby="describedby">
                <option value="llm">Par le modèle (par défaut)</option>
                <option value="paragraph">Par paragraphe</option>
                <option value="fixed">Taille fixe</option>
                <option value="semantic">Sémantique</option>
              </select>
            </template>
          </SettingsField>
          <SettingsField
            v-if="draft.chunking.strategy === 'llm'"
            id="instructions-chunking"
            label="Consignes de découpage"
            optional
          >
            <template #default="{ id }">
              <textarea
                :id="id"
                v-model="draft.instructions.chunking"
                rows="2"
                placeholder="Ex. Ne jamais couper une clause juridique en deux chunks."
              />
            </template>
          </SettingsField>

          <template #advanced>
            <div v-if="draft.chunking.strategy === 'paragraph' || draft.chunking.strategy === 'fixed'" class="sf-grid">
              <SettingsField id="chunk-size" label="Taille des chunks (tokens)" :error="errors.chunkSize" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.chunking.chunkSize" type="number" min="64" max="4096" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField
                id="chunk-overlap"
                label="Chevauchement (tokens)"
                hint="Tokens répétés entre deux chunks consécutifs, pour ne pas perdre le contexte à la coupure."
                :error="errors.chunkOverlap"
                short
              >
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.chunking.chunkOverlap" type="number" min="0" max="512" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
            </div>
            <div v-if="draft.chunking.strategy === 'semantic'" class="sf-grid">
              <SettingsField id="chunking-window-pages" label="Pages lues à la fois" :error="errors.chunkingWindowPages" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.chunkingWindowPages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField
                id="chunking-slide-pages"
                label="Avancée entre deux lectures (pages)"
                hint="Plus petite que les pages lues à la fois, les lectures se recouvrent."
                :error="errors.chunkingSlidePages"
                short
              >
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.chunkingSlidePages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
            </div>
            <SettingsField v-if="draft.chunking.strategy === 'llm'" id="model-chunking" label="Modèle utilisé pour le découpage">
              <template #default="{ id }"><ModelSelect :id="id" v-model="draft.models.chunking" /></template>
            </SettingsField>
            <p v-if="draft.chunking.strategy === 'llm' || draft.chunking.strategy === 'fixed' || draft.chunking.strategy === 'paragraph'" class="sf-hint">
              <template v-if="draft.chunking.strategy === 'llm'">Le modèle choisit lui-même la taille des chunks.</template>
              <template v-else>Les pages lues à la fois ne concernent que le découpage sémantique.</template>
            </p>
          </template>
        </SettingsSection>

        <SettingsSection
          title="Modèle d'embedding"
          :summary="draft.embeddingModel || 'Non choisi'"
          :changed="isChanged('embedding')"
        >
          <SettingsField
            id="embedding-model"
            label="Modèle d'embedding"
            hint="Il sert à retrouver les passages qui répondent à une question. Changer de modèle rend les vecteurs déjà calculés incompatibles : l'index doit être reconstruit. La recherche continue d'utiliser l'index actuel jusqu'à la bascule."
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

          <div v-if="indexRebuild?.status === 'building'" class="sf-callout" role="status">
            <p>
              Réindexation en cours avec « {{ indexRebuild.targetModel }} » ({{ indexRebuild.donePoints }} /
              {{ indexRebuild.totalPoints }}). La recherche continue d'utiliser l'index actuel
              (« {{ indexRebuild.previousModel }} ») jusqu'à la bascule.
            </p>
            <progress :max="indexRebuild.totalPoints || 1" :value="indexRebuild.donePoints"></progress>
          </div>

          <div v-else-if="indexRebuild?.status === 'swapped'" class="sf-callout" role="status">
            <p>
              Le nouvel index (« {{ indexRebuild.targetModel }} ») est actif. L'ancien est conservé : validez la
              bascule pour le supprimer, ou revenez à l'ancien index.
            </p>
            <div class="sf-actions">
              <button type="button" class="fr-btn fr-btn--sm" @click="finalizeIndexRebuild(collection.id)">
                Valider la bascule
              </button>
              <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="rollbackIndexRebuild(collection.id)">
                Revenir à l'ancien index
              </button>
            </div>
          </div>

          <div v-if="collection.reindexRequired && indexRebuild?.status !== 'building'" class="sf-callout sf-callout--warning">
            <p>
              Le modèle d'embedding a changé : l'index contient encore les vecteurs de
              « {{ collection.indexEmbeddingModel ?? collection.embeddingModel }} » et reste utilisé pour la recherche
              tant qu'il n'est pas reconstruit avec « {{ collection.embeddingModel }} ».
            </p>
            <p v-if="indexRebuild?.status === 'failed'">La dernière réindexation a échoué : {{ indexRebuild.error }}</p>
            <div class="sf-actions">
              <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="reindexCollection(collection.id)">
                Réindexer maintenant
              </button>
            </div>
          </div>
          <p v-if="indexRebuildError" class="sf-error" role="alert">{{ indexRebuildError }}</p>
        </SettingsSection>
      </section>

      <section class="settings-tab__group" aria-labelledby="group-enrich">
        <h3 id="group-enrich" class="settings-tab__group-title">Ce que l'IA ajoute à chaque document</h3>
        <div class="settings-tab__common-model">
          <SettingsField
            id="model-all"
            label="Modèle de génération"
            hint="Le même pour toutes les étapes ci-dessous. Un modèle différent par étape se choisit dans leurs réglages avancés."
          >
            <template #default="{ id, describedby }">
              <ModelSelect :id="id" v-model="generationModel" :describedby="describedby" :mixed="modelsDiffer" />
            </template>
          </SettingsField>
        </div>

        <SettingsSection
          title="Résumé"
          :summary="stepSummary(draft, 'summary')"
          :changed="isChanged('summary')"
          :invalid="invalid.summary"
          :force-open="invalid.summary"
        >
          <p class="sf-hint">Chaque document reçoit un résumé, que l'assistant utilise pour savoir de quoi il parle.</p>
          <SettingsField id="instructions-summary" label="Consignes pour le résumé" optional>
            <template #default="{ id }">
              <textarea
                :id="id"
                v-model="draft.instructions.summary"
                rows="2"
                placeholder="Ex. Rédiger un résumé factuel de 5 lignes maximum, sans jugement."
              />
            </template>
          </SettingsField>
          <template #advanced>
            <SettingsField id="model-summary" label="Modèle pour le résumé">
              <template #default="{ id }"><ModelSelect :id="id" v-model="draft.models.summary" /></template>
            </SettingsField>
            <SettingsField
              id="summary-pages-per-map"
              label="Pages résumées ensemble"
              hint="Le résumé se fait par lots de pages, puis les résumés partiels sont assemblés. Un lot plus grand fait moins d'appels, mais des résumés moins détaillés."
              :error="errors.summaryPagesPerMap"
              short
            >
              <template #default="{ id, describedby, invalid: isInvalid }">
                <input :id="id" v-model.number="draft.windows.summaryPagesPerMap" type="number" min="1" max="50" :aria-describedby="describedby" :aria-invalid="isInvalid" />
              </template>
            </SettingsField>
          </template>
        </SettingsSection>

        <SettingsSection
          title="Questions-réponses"
          :summary="stepSummary(draft, 'qa')"
          :changed="isChanged('qa')"
          :invalid="invalid.qa"
          :force-open="invalid.qa"
        >
          <p class="sf-hint">
            Des questions-réponses sont générées à partir des documents : elles servent de réponses toutes prêtes et
            à évaluer la qualité de la recherche.
          </p>
          <SettingsField id="instructions-qa" label="Consignes pour les questions" optional>
            <template #default="{ id }">
              <textarea
                :id="id"
                v-model="draft.instructions.qa"
                rows="2"
                placeholder="Ex. Formuler des questions courtes, orientées agents publics."
              />
            </template>
          </SettingsField>
          <template #advanced>
            <SettingsField id="model-qa" label="Modèle pour les questions">
              <template #default="{ id }"><ModelSelect :id="id" v-model="draft.models.qa" /></template>
            </SettingsField>
            <div class="sf-grid">
              <SettingsField id="qa-window-pages" label="Pages lues à la fois" hint="Les pages fournies au modèle pour écrire des questions." :error="errors.qaWindowPages" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.qaWindowPages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField id="qa-slide-pages" label="Avancée entre deux lectures (pages)" hint="Plus petite que les pages lues à la fois, les lectures se recouvrent." :error="errors.qaSlidePages" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.qaSlidePages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField id="qa-questions-per-window" label="Questions par lecture" :error="errors.qaQuestionsPerWindow" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.qaQuestionsPerWindow" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField
                id="collection-qa-count"
                label="Questions sur la description de la collection"
                hint="Générées à partir de la description (pas d'un document), à chaque fois qu'elle change."
                :error="errors.collectionQaCount"
                short
              >
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.collectionQaCount" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
            </div>
          </template>
        </SettingsSection>

        <SettingsSection
          title="Entités et relations"
          :summary="stepSummary(draft, 'extraction')"
          :changed="isChanged('extraction')"
          :invalid="invalid.extraction"
          :force-open="invalid.extraction"
        >
          <p class="sf-hint">Les personnes, organisations, lieux… cités dans les documents, et les liens entre eux.</p>
          <SettingsField id="instructions-extraction" label="Consignes pour l'extraction" optional>
            <template #default="{ id }">
              <textarea
                :id="id"
                v-model="draft.instructions.extraction"
                rows="2"
                placeholder="Ex. Prioriser les entités de type organisation et ignorer les dates relatives."
              />
            </template>
          </SettingsField>
          <template #advanced>
            <SettingsField id="model-extraction" label="Modèle pour l'extraction">
              <template #default="{ id }"><ModelSelect :id="id" v-model="draft.models.extraction" /></template>
            </SettingsField>
            <div class="sf-grid">
              <SettingsField id="extraction-window-pages" label="Pages lues à la fois" :error="errors.extractionWindowPages" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.extractionWindowPages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
              <SettingsField id="extraction-slide-pages" label="Avancée entre deux lectures (pages)" hint="Plus petite que les pages lues à la fois, les lectures se recouvrent." :error="errors.extractionSlidePages" short>
                <template #default="{ id, describedby, invalid: isInvalid }">
                  <input :id="id" v-model.number="draft.windows.extractionSlidePages" type="number" min="1" max="20" :aria-describedby="describedby" :aria-invalid="isInvalid" />
                </template>
              </SettingsField>
            </div>
          </template>
        </SettingsSection>

        <SettingsSection title="Tags" :summary="stepSummary(draft, 'tagging')" :changed="isChanged('tagging')">
          <p class="sf-hint">Des tags sont ajoutés automatiquement à chaque document pour le retrouver.</p>
          <SettingsField id="instructions-tagging" label="Consignes pour les tags" optional>
            <template #default="{ id }">
              <textarea
                :id="id"
                v-model="draft.instructions.tagging"
                rows="2"
                placeholder="Ex. Utiliser au plus 5 tags, en minuscules, sans accents."
              />
            </template>
          </SettingsField>
          <template #advanced>
            <SettingsField id="model-tagging" label="Modèle pour les tags">
              <template #default="{ id }"><ModelSelect :id="id" v-model="draft.models.tagging" /></template>
            </SettingsField>
          </template>
        </SettingsSection>
      </section>

      <section class="settings-tab__group" aria-labelledby="group-long">
        <h3 id="group-long" class="settings-tab__group-title">Documents très longs</h3>
        <SettingsSection
          title="Ce qui est lu d'un long document"
          :summary="longDocsSummary(draft)"
          :changed="isChanged('longDocs')"
          :invalid="invalid.longDocs"
          :force-open="invalid.longDocs"
        >
          <LongDocumentsFields
            :long-docs="draft.longDocs"
            :errors="errors"
            :collection-id="collection.id"
            :chunking-strategy="draft.chunking.strategy"
          />
        </SettingsSection>
      </section>

      <section class="settings-tab__group" aria-labelledby="group-access">
        <h3 id="group-access" class="settings-tab__group-title">Qui peut y accéder</h3>
        <p class="sf-hint">Ces deux réglages s'appliquent tout de suite, sans passer par « Enregistrer ».</p>
        <CollectionAccessSettings :collection="collection" />
      </section>

      <div class="settings-tab__bar" role="region" aria-label="Enregistrement des paramètres">
        <p v-if="saveError" class="sf-error" role="alert">{{ saveError }}</p>
        <p v-else-if="hasErrors" class="sf-error" role="status">Corrigez les champs signalés : {{ invalidLabels }}.</p>
        <p v-else-if="changed.length" class="settings-tab__bar-text" role="status">
          Non enregistré : {{ changedLabels }}.
        </p>
        <p v-else-if="justSaved" class="settings-tab__bar-text" role="status">Paramètres enregistrés.</p>
        <p v-else class="settings-tab__bar-text">Aucune modification.</p>
        <div class="sf-actions">
          <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" :disabled="!changed.length || saving" @click="discard">
            Annuler les modifications
          </button>
          <button type="button" class="fr-btn fr-btn--sm" :disabled="!changed.length || hasErrors || saving" @click="save">
            {{ saving ? 'Enregistrement…' : 'Enregistrer' }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.settings-tab {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.settings-tab__intro {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.settings-tab__group {
  display: flex;
  flex-direction: column;
  gap: 0.625rem;
}

.settings-tab__group-title {
  margin: 0;
  font-size: 1.0625rem;
}

.settings-tab__common-model {
  padding: 0.875rem 1rem;
  border-radius: 0.75rem;
  background: var(--background-alt-grey);
}

/* Toujours visible : on enregistre sans remonter tout en haut, et on voit d'un coup d'œil ce qui est en attente. */
.settings-tab__bar {
  position: sticky;
  bottom: 0;
  z-index: 5;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
}

.settings-tab__bar p {
  margin: 0;
}

.settings-tab__bar-text {
  font-size: 0.875rem;
}
</style>
