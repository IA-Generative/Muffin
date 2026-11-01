<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAdminGuardrails } from '../composables/useAdminGuardrails'
import { useAssistants } from '../composables/useAssistants'
import type { Guardrail, GuardrailDraft, GuardrailType } from '../types/guardrail'
import {
  BUILTINS,
  ENFORCEMENT_HINTS,
  ENFORCEMENT_LABELS,
  TYPE_LABELS,
  cleanConfig,
  draftOf,
  emptyDraft,
  splitList,
  tryPattern,
} from '../utils/guardrails'

const props = defineProps<{ guardrail: Guardrail | null }>()
const emit = defineEmits<{ saved: []; cancel: [] }>()

const { save } = useAdminGuardrails()
const { assistants, refreshAssistants } = useAssistants()

const draft = reactive<GuardrailDraft>(emptyDraft())
// Ce qu'on tape n'est pas ce qu'on envoie : des listes en lignes, des motifs avec un essai en direct.
const termsText = ref('')
const categoriesText = ref('')
const groupsText = ref('')
const sample = ref('')
const message = ref<string | null>(null)
const saving = ref(false)

onMounted(() => {
  if (!assistants.value.length) void refreshAssistants()
})

watch(
  () => props.guardrail,
  (guardrail) => {
    Object.assign(draft, guardrail ? draftOf(guardrail) : emptyDraft())
    termsText.value = (draft.config.terms ?? []).join('\n')
    categoriesText.value = (draft.config.categories ?? []).join(', ')
    groupsText.value = draft.scopeGroups.join(', ')
  },
  { immediate: true },
)

const creating = computed(() => props.guardrail === null)
const hasRedaction = computed(() => draft.type !== 'llm')
const enforcements = computed(() =>
  (Object.keys(ENFORCEMENT_LABELS) as (keyof typeof ENFORCEMENT_LABELS)[]).filter(
    (mode) => mode !== 'redact' || hasRedaction.value,
  ),
)

function changeType(type: GuardrailType) {
  const fresh = emptyDraft(type)
  draft.type = type
  draft.config = fresh.config
  draft.stage = fresh.stage
  if (type === 'llm' && draft.enforcement === 'redact') draft.enforcement = 'monitor'
  termsText.value = ''
  categoriesText.value = ''
}

function toggleBuiltin(key: string) {
  const list = draft.config.builtins ?? []
  draft.config.builtins = list.includes(key) ? list.filter((item) => item !== key) : [...list, key]
}

function addPattern() {
  draft.config.patterns = [...(draft.config.patterns ?? []), { name: '', regex: '', label: '' }]
}

function removePattern(index: number) {
  draft.config.patterns = (draft.config.patterns ?? []).filter((_, position) => position !== index)
}

function toggleAssistant(id: string) {
  draft.scopeAssistants = draft.scopeAssistants.includes(id)
    ? draft.scopeAssistants.filter((item) => item !== id)
    : [...draft.scopeAssistants, id]
}

const canSave = computed(
  () =>
    !!draft.name.trim() &&
    !saving.value &&
    (draft.type !== 'http' || !!draft.config.url?.trim()) &&
    (draft.config.patterns ?? []).every((pattern) => tryPattern(pattern.regex, '').valid),
)

async function submit() {
  if (!canSave.value) return
  saving.value = true
  message.value = null
  draft.config.terms = splitList(termsText.value)
  draft.config.categories = splitList(categoriesText.value)
  draft.scopeGroups = splitList(groupsText.value)
  const body: GuardrailDraft = { ...draft, config: cleanConfig(draft.type, draft.config) }
  const refusal = await save(body, props.guardrail?.id)
  saving.value = false
  if (refusal) message.value = refusal
  else emit('saved')
}
</script>

<template>
  <form class="guardrail-form" @submit.prevent="submit">
    <h2 class="guardrail-form__title">{{ creating ? 'Nouveau garde-fou' : `Modifier « ${guardrail?.name} »` }}</h2>

    <div class="guardrail-form__row">
      <div class="guardrail-form__field guardrail-form__field--wide">
        <label for="gr-name">Nom</label>
        <input id="gr-name" v-model="draft.name" class="fr-input" type="text" maxlength="100" required />
      </div>
      <div v-if="creating" class="guardrail-form__field">
        <label for="gr-type">Type</label>
        <select id="gr-type" :value="draft.type" class="fr-select" @change="changeType(($event.target as HTMLSelectElement).value as GuardrailType)">
          <option v-for="(label, type) in TYPE_LABELS" :key="type" :value="type">{{ label }}</option>
        </select>
      </div>
    </div>
    <div class="guardrail-form__field">
      <label for="gr-description">Description</label>
      <input id="gr-description" v-model="draft.description" class="fr-input" type="text" maxlength="1000" />
    </div>

    <!-- Les réglages du type -->
    <fieldset v-if="draft.type === 'rules'" class="guardrail-form__group">
      <legend>Ce qu'il cherche</legend>
      <div v-for="builtin in BUILTINS" :key="builtin.key" class="fr-checkbox-group">
        <input :id="`gr-builtin-${builtin.key}`" type="checkbox" :checked="draft.config.builtins?.includes(builtin.key)" @change="toggleBuiltin(builtin.key)" />
        <label class="fr-label" :for="`gr-builtin-${builtin.key}`">
          {{ builtin.label }}
          <span class="fr-hint-text">{{ builtin.hint }}</span>
        </label>
      </div>
      <div class="guardrail-form__field">
        <label for="gr-sample">Essayer les motifs sur un texte</label>
        <textarea id="gr-sample" v-model="sample" class="fr-input" rows="2" placeholder="Collez ici un exemple : les motifs ci-dessous disent combien de fois ils s’y trouvent" />
      </div>
      <div v-for="(pattern, index) in draft.config.patterns" :key="index" class="guardrail-form__pattern">
        <input v-model="pattern.name" class="fr-input" type="text" :aria-label="`Nom du motif ${index + 1}`" placeholder="Nom (devient le marqueur [NOM])" />
        <input v-model="pattern.regex" class="fr-input" type="text" :aria-label="`Motif ${index + 1}`" placeholder="Expression régulière, ex. DOS-\d{6}" maxlength="500" />
        <span
          class="guardrail-form__match"
          :class="{ 'guardrail-form__match--bad': !tryPattern(pattern.regex, sample).valid }"
          role="status"
        >
          {{ !tryPattern(pattern.regex, sample).valid ? 'Motif invalide' : sample ? `${tryPattern(pattern.regex, sample).matches} trouvé(s)` : '' }}
        </span>
        <button type="button" class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm" @click="removePattern(index)">Retirer</button>
      </div>
      <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="addPattern">Ajouter un motif</button>
      <div class="guardrail-form__field">
        <label for="gr-terms">Termes interdits (un par ligne)</label>
        <textarea id="gr-terms" v-model="termsText" class="fr-input" rows="3" />
      </div>
      <div class="guardrail-form__row">
        <div class="guardrail-form__field">
          <label for="gr-max">Longueur maximale (caractères)</label>
          <input id="gr-max" v-model.number="draft.config.max_chars" class="fr-input" type="number" min="1" placeholder="Aucune" />
        </div>
        <div class="guardrail-form__field">
          <label for="gr-category">Catégorie enregistrée</label>
          <input id="gr-category" v-model="draft.config.category" class="fr-input" type="text" maxlength="64" />
        </div>
      </div>
    </fieldset>

    <fieldset v-else-if="draft.type === 'llm'" class="guardrail-form__group">
      <legend>Le juge</legend>
      <p class="guardrail-form__hint">
        Un modèle du hub classe la demande en un JSON strict ; la demande est placée entre des délimiteurs et traitée comme
        une donnée. <strong>Ce n’est pas une garantie</strong> : un modèle peut être contourné. Coûte un appel de plus, en
        parallèle, décompté sous l’étape <code>guardrail:nom</code>.
      </p>
      <div class="guardrail-form__field">
        <label for="gr-prompt">Consignes du juge (vide : celles par défaut, contre l’injection de consignes)</label>
        <textarea id="gr-prompt" v-model="draft.config.prompt" class="fr-input" rows="4" maxlength="4000" />
      </div>
      <div class="guardrail-form__row">
        <div class="guardrail-form__field">
          <label for="gr-categories">Catégories possibles (séparées par des virgules)</label>
          <input id="gr-categories" v-model="categoriesText" class="fr-input" type="text" />
        </div>
        <div class="guardrail-form__field">
          <label for="gr-threshold">Seuil (0 à 1)</label>
          <input id="gr-threshold" v-model.number="draft.config.threshold" class="fr-input" type="number" min="0" max="1" step="0.05" />
        </div>
        <div class="guardrail-form__field">
          <label for="gr-model">Modèle (vide : le premier modèle de discussion du hub)</label>
          <input id="gr-model" v-model="draft.config.model" class="fr-input" type="text" />
        </div>
      </div>
    </fieldset>

    <fieldset v-else class="guardrail-form__group">
      <legend>Le service</legend>
      <p class="guardrail-form__hint">
        Muffin envoie <code>POST {adresse}</code> avec <code>{"text", "language"}</code> et attend
        <code>{"flagged", "category", "score", "redacted_text"}</code>. https, adresse publique, aucune redirection suivie.
      </p>
      <div class="guardrail-form__field">
        <label for="gr-url">Adresse</label>
        <input id="gr-url" v-model="draft.config.url" class="fr-input" type="url" placeholder="https://…" required />
      </div>
      <div class="guardrail-form__field">
        <label for="gr-key">Clé du service</label>
        <input id="gr-key" v-model="draft.apiKey" class="fr-input" type="password" autocomplete="off" />
        <p class="guardrail-form__hint">
          {{ draft.clearKey ? 'La clé enregistrée sera oubliée.' : guardrail?.hasKey ? 'Une clé est enregistrée, chiffrée. Elle ne s’affiche jamais : saisissez-en une autre pour la remplacer.' : 'Facultative. Chiffrée, jamais relue.' }}
        </p>
        <div v-if="guardrail?.hasKey" class="fr-checkbox-group">
          <input id="gr-clear-key" v-model="draft.clearKey" type="checkbox" />
          <label class="fr-label" for="gr-clear-key">Oublier la clé enregistrée</label>
        </div>
      </div>
    </fieldset>

    <!-- Ce qu'il fait -->
    <fieldset class="guardrail-form__group">
      <legend>Ce qu'il fait</legend>
      <div v-for="mode in enforcements" :key="mode" class="fr-radio-group">
        <input :id="`gr-mode-${mode}`" v-model="draft.enforcement" type="radio" :value="mode" />
        <label class="fr-label" :for="`gr-mode-${mode}`">
          {{ ENFORCEMENT_LABELS[mode] }}
          <span class="fr-hint-text">{{ ENFORCEMENT_HINTS[mode] }}</span>
        </label>
      </div>
      <div class="guardrail-form__field">
        <label for="gr-refusal">Message montré à la personne (bloquer ou avertir)</label>
        <textarea id="gr-refusal" v-model="draft.refusalMessage" class="fr-input" rows="2" maxlength="1000" aria-describedby="gr-refusal-hint" />
        <p id="gr-refusal-hint" class="guardrail-form__hint">Neutre de préférence : il ne doit pas révéler la règle exacte, qu’on contournerait par tâtonnement. Vide : le message par défaut de la politique.</p>
      </div>
      <div class="guardrail-form__field">
        <label for="gr-label">Catégorie générale nommable dans le refus (si la politique le permet)</label>
        <input id="gr-label" v-model="draft.categoryLabel" class="fr-input" type="text" maxlength="100" placeholder="données personnelles" />
      </div>
    </fieldset>

    <fieldset class="guardrail-form__group">
      <legend>Quand et pour qui</legend>
      <div class="guardrail-form__row">
        <div class="guardrail-form__field">
          <label for="gr-stage">Étape</label>
          <input id="gr-stage" v-model.number="draft.stage" class="fr-input" type="number" min="1" max="9" aria-describedby="gr-stage-hint" />
        </div>
        <div class="guardrail-form__field">
          <label for="gr-timeout">Délai (ms)</label>
          <input id="gr-timeout" v-model.number="draft.timeoutMs" class="fr-input" type="number" min="20" step="100" />
        </div>
        <div class="guardrail-form__field">
          <label for="gr-on-error">En cas de panne ou de délai dépassé</label>
          <select id="gr-on-error" v-model="draft.onError" class="fr-select">
            <option value="fail_open">Laisser passer (fail open)</option>
            <option value="fail_closed">Bloquer (fail closed)</option>
          </select>
        </div>
      </div>
      <p id="gr-stage-hint" class="guardrail-form__hint">Les garde-fous d’une étape partent ensemble ; l’étape 2 ne part que si la demande a passé l’étape 1 : mettez les contrôles gratuits en premier.</p>
      <div class="fr-checkbox-group">
        <input id="gr-critical" v-model="draft.critical" type="checkbox" />
        <label class="fr-label" for="gr-critical">Critique : s’il ne peut pas répondre, la demande s’arrête, même en « laisser passer »</label>
      </div>
      <div class="guardrail-form__field">
        <label for="gr-groups">Groupes concernés (séparés par des virgules ; vide avec aucun assistant : tout le monde)</label>
        <input id="gr-groups" v-model="groupsText" class="fr-input" type="text" />
      </div>
      <fieldset v-if="assistants.length" class="guardrail-form__field">
        <legend class="guardrail-form__sub">Assistants concernés</legend>
        <div v-for="assistant in assistants" :key="assistant.id" class="fr-checkbox-group">
          <input :id="`gr-assistant-${assistant.id}`" type="checkbox" :checked="draft.scopeAssistants.includes(assistant.id)" @change="toggleAssistant(assistant.id)" />
          <label class="fr-label" :for="`gr-assistant-${assistant.id}`">{{ assistant.name }}</label>
        </div>
      </fieldset>
      <div class="fr-checkbox-group">
        <input id="gr-enabled" v-model="draft.enabled" type="checkbox" />
        <label class="fr-label" for="gr-enabled">Activé</label>
      </div>
    </fieldset>

    <p v-if="message" class="guardrail-form__error" role="alert">{{ message }}</p>
    <div class="guardrail-form__actions">
      <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
      <button type="submit" class="fr-btn" :disabled="!canSave">{{ saving ? 'Enregistrement…' : 'Enregistrer' }}</button>
    </div>
  </form>
</template>

<style scoped>
.guardrail-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 56rem;
  margin: 0 auto 1.5rem;
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.guardrail-form__title {
  margin: 0;
  font-size: 1.125rem;
}

.guardrail-form__group {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 0;
  padding: 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.guardrail-form__group > legend,
.guardrail-form__sub {
  padding: 0 0.375rem;
  font-size: 0.875rem;
  font-weight: 700;
}

.guardrail-form__field {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.375rem;
  min-width: 10rem;
  border: none;
  margin: 0;
  padding: 0;
}

.guardrail-form__field--wide {
  flex: 3;
}

.guardrail-form__field > label {
  font-size: 0.875rem;
  font-weight: 700;
}

.guardrail-form__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.guardrail-form__pattern {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.guardrail-form__pattern .fr-input {
  flex: 1;
  min-width: 10rem;
}

.guardrail-form__match {
  min-width: 7rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.guardrail-form__match--bad,
.guardrail-form__error {
  color: var(--text-default-error);
}

.guardrail-form__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.guardrail-form__error {
  margin: 0;
  font-size: 0.875rem;
}

.guardrail-form__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
</style>
