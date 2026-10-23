<script setup lang="ts">
// Les réglages des longs documents (#372) et leur coût : ce que le résumé, les questions et les entités lisent
// d'un document de plusieurs centaines de pages. Modifie directement le brouillon réactif du parent.
import { computed } from 'vue'
import '../assets/settings-form.css'
import { useIndexingEstimate } from '../composables/useIndexingEstimate'
import { setSeparateEnds, type LongDocumentsDraft } from '../utils/longDocuments'
import type { SettingsErrors } from '../utils/settingsDraft'
import SettingsField from './SettingsField.vue'

const props = defineProps<{
  longDocs: LongDocumentsDraft
  errors: SettingsErrors
  collectionId: string
  chunkingStrategy: string
}>()

const LONG_DOCS_FIELDS = [
  'samplingMinPages',
  'summaryPercent',
  'summaryHeadPercent',
  'summaryTailPercent',
  'summaryPageRanges',
  'qaMaxQuestions',
  'extractionPercent',
  'extractionMaxWindows',
] as const
const longDocsInvalid = computed(() => LONG_DOCS_FIELDS.some((field) => props.errors[field]))

const { pages, pagesInvalid, state, steps, embeddings } = useIndexingEstimate({
  collectionId: () => props.collectionId,
  longDocs: () => props.longDocs,
  chunkingStrategy: () => props.chunkingStrategy,
  valid: () => !longDocsInvalid.value,
})

const separateEnds = computed({
  get: () => props.longDocs.separateEnds,
  set: (value: boolean) => setSeparateEnds(props.longDocs, value),
})
</script>

<template>
  <div class="sf-stack">
    <p class="sf-hint">
      Au-delà d'un certain nombre de pages, le résumé, les questions et les entités peuvent ne lire qu'une partie du
      document pour limiter les appels au modèle. Par défaut, tout est lu. Le découpage (chunks) couvre toujours tout
      le document.
    </p>

    <SettingsField
      id="long-docs-min-pages"
      label="À partir de combien de pages"
      hint="En deçà, tout le document est traité normalement, quels que soient les réglages ci-dessous."
      :error="errors.samplingMinPages"
      short
    >
      <template #default="{ id, describedby, invalid }">
        <input
          :id="id"
          v-model.number="longDocs.samplingMinPages"
          type="number"
          min="1"
          :aria-describedby="describedby"
          :aria-invalid="invalid"
        />
      </template>
    </SettingsField>

    <fieldset class="long-docs__group">
      <legend class="sf-label">Résumé</legend>
      <div class="fr-radio-group fr-radio-group--sm">
        <input id="long-docs-summary-all" v-model="longDocs.summaryMode" type="radio" value="all" name="long-docs-summary-mode" />
        <label class="fr-label" for="long-docs-summary-all">Tout le document</label>
      </div>
      <div class="fr-radio-group fr-radio-group--sm">
        <input id="long-docs-summary-percent" v-model="longDocs.summaryMode" type="radio" value="percent" name="long-docs-summary-mode" />
        <label class="fr-label" for="long-docs-summary-percent">Une partie du document</label>
      </div>
      <div class="fr-radio-group fr-radio-group--sm">
        <input id="long-docs-summary-pages" v-model="longDocs.summaryMode" type="radio" value="pages" name="long-docs-summary-mode" />
        <label class="fr-label" for="long-docs-summary-pages">Des pages précises</label>
      </div>

      <template v-if="longDocs.summaryMode === 'percent'">
        <SettingsField
          v-if="!longDocs.separateEnds"
          id="long-docs-summary-percent-value"
          label="Part du document lue (%)"
          hint="Répartie moitié au début, moitié à la fin du document."
          :error="errors.summaryPercent"
          short
        >
          <template #default="{ id, describedby, invalid }">
            <input :id="id" v-model.number="longDocs.summaryPercent" type="number" min="1" max="100" :aria-describedby="describedby" :aria-invalid="invalid" />
          </template>
        </SettingsField>
        <div v-else class="sf-grid">
          <SettingsField id="long-docs-summary-head" label="Début du document lu (%)" :error="errors.summaryHeadPercent" short>
            <template #default="{ id, describedby, invalid }">
              <input :id="id" v-model.number="longDocs.summaryHeadPercent" type="number" min="0" max="100" :aria-describedby="describedby" :aria-invalid="invalid" />
            </template>
          </SettingsField>
          <SettingsField id="long-docs-summary-tail" label="Fin du document lue (%)" :error="errors.summaryTailPercent" short>
            <template #default="{ id, describedby, invalid }">
              <input :id="id" v-model.number="longDocs.summaryTailPercent" type="number" min="0" max="100" :aria-describedby="describedby" :aria-invalid="invalid" />
            </template>
          </SettingsField>
        </div>
        <div class="fr-checkbox-group fr-checkbox-group--sm">
          <input id="long-docs-separate" v-model="separateEnds" type="checkbox" />
          <label class="fr-label" for="long-docs-separate">Régler le début et la fin séparément</label>
        </div>
      </template>

      <SettingsField
        v-if="longDocs.summaryMode === 'pages'"
        id="long-docs-summary-ranges"
        label="Pages lues"
        hint="Des pages ou des plages séparées par des virgules, par exemple 1-5, 40-45, 90- (jusqu'à la fin)."
        :error="errors.summaryPageRanges"
      >
        <template #default="{ id, describedby, invalid }">
          <input :id="id" v-model="longDocs.summaryPageRanges" type="text" inputmode="numeric" placeholder="1-5, 40-45, 90-" :aria-describedby="describedby" :aria-invalid="invalid" />
        </template>
      </SettingsField>

      <p class="sf-hint">
        Un résumé partiel ne dit rien des pages non lues : il le signale, et l'assistant ne s'en sert pas pour répondre
        sur un détail qu'elles pourraient ne pas couvrir.
      </p>
    </fieldset>

    <SettingsField
      id="long-docs-qa-max"
      label="Nombre maximum de questions par document"
      optional
      hint="Vide : pas de plafond. Les questions sont posées sur des pages tirées sur tout le document, jamais plus que ce nombre (parfois moins). Avec moins de questions, une question posée a moins de chances de retomber sur une question déjà générée."
      :error="errors.qaMaxQuestions"
      short
    >
      <template #default="{ id, describedby, invalid }">
        <input :id="id" v-model.number="longDocs.qaMaxQuestions" type="number" min="1" placeholder="Illimité" :aria-describedby="describedby" :aria-invalid="invalid" />
      </template>
    </SettingsField>

    <div class="sf-grid">
      <SettingsField
        id="long-docs-entities-percent"
        label="Part du document analysée pour les entités (%)"
        hint="Les entités et relations ne sont extraites que d'un échantillon des pages : le graphe est plus pauvre qu'en lisant tout."
        :error="errors.extractionPercent"
        short
      >
        <template #default="{ id, describedby, invalid }">
          <input :id="id" v-model.number="longDocs.extractionPercent" type="number" min="1" max="100" :aria-describedby="describedby" :aria-invalid="invalid" />
        </template>
      </SettingsField>
      <SettingsField
        id="long-docs-entities-max"
        label="Nombre maximum de fenêtres analysées"
        optional
        :error="errors.extractionMaxWindows"
        short
      >
        <template #default="{ id, describedby, invalid }">
          <input :id="id" v-model.number="longDocs.extractionMaxWindows" type="number" min="1" placeholder="Illimité" :aria-describedby="describedby" :aria-invalid="invalid" />
        </template>
      </SettingsField>
    </div>

    <div class="sf-callout" aria-live="polite">
      <SettingsField id="long-docs-estimate-pages" label="Estimer pour un document de (pages)" short>
        <template #default="{ id }">
          <input :id="id" v-model.number="pages" type="number" min="1" max="100000" :aria-invalid="pagesInvalid ? 'true' : undefined" />
        </template>
      </SettingsField>
      <p v-if="longDocsInvalid || pagesInvalid" class="sf-hint">Corriger les champs signalés pour voir l'estimation.</p>
      <p v-else-if="state.error" class="sf-error">{{ state.error }}</p>
      <template v-else-if="state.draft">
        <p>
          Environ <strong>{{ state.draft.chat.total }} appels</strong> au modèle pour un document de
          {{ state.draft.pages }} pages<template v-if="state.full && state.full.chat.total !== state.draft.chat.total">
            (au lieu de {{ state.full.chat.total }} en lisant tout)</template>.
        </p>
        <p v-if="!state.draft.sampled" class="sf-hint">Ce document n'atteint pas le seuil : tout est lu, comme avant.</p>
        <ul class="long-docs__steps">
          <li v-for="step in steps" :key="step.key">{{ step.label }} : {{ step.calls }}</li>
        </ul>
        <p class="sf-hint">
          À part : {{ embeddings }} appels au modèle d'embedding (le résumé, et une par question) ; le découpage et les
          passages en ajoutent selon leur taille.
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.long-docs__group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  border: 0;
}

.long-docs__group legend {
  padding: 0;
}

.long-docs__steps {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.8125rem;
}
</style>
