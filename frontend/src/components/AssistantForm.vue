<script setup lang="ts">
// Créer ou modifier un assistant : un nom, des consignes, des collections et des outils. C'est le même agent que dans le
// chat sans assistant ; seuls ces quatre réglages changent.
import { computed, reactive, watch } from 'vue'
import { useAssistants } from '../composables/useAssistants'
import { useCollections } from '../composables/useCollections'
import { OPTIONAL_TOOLS, type Assistant, type AssistantDraft } from '../types/assistant'

const props = defineProps<{ assistant: Assistant | null }>()
const emit = defineEmits<{ saved: [assistant: Assistant]; cancel: [] }>()

const MAX_INSTRUCTIONS = 4000
const MAX_SUGGESTIONS = 6

const { saveAssistant, assistantError } = useAssistants()
const { collections } = useCollections()

function fromAssistant(assistant: Assistant | null): AssistantDraft {
  return {
    name: assistant?.name ?? '',
    description: assistant?.description ?? '',
    icon: assistant?.icon ?? '',
    instructions: assistant?.instructions ?? '',
    hideInstructions: assistant?.hideInstructions ?? false,
    collectionIds: assistant?.collections.map((collection) => collection.id) ?? [],
    includeDescendants: assistant?.includeDescendants ?? true,
    webSearchAllowed: assistant?.webSearchAllowed ?? false,
    disabledTools: [...(assistant?.disabledTools ?? [])],
    suggestions: (assistant?.suggestions ?? []).join('\n'),
  }
}

const draft = reactive<AssistantDraft>(fromAssistant(props.assistant))
watch(
  () => props.assistant?.id,
  () => Object.assign(draft, fromAssistant(props.assistant)),
)

const suggestionCount = computed(() => draft.suggestions.split('\n').filter((line) => line.trim()).length)
const problems = computed(() => {
  const list: string[] = []
  if (!draft.name.trim()) list.push('Donnez un nom à l’assistant.')
  if (draft.instructions.length > MAX_INSTRUCTIONS) list.push(`Les consignes dépassent ${MAX_INSTRUCTIONS} caractères.`)
  if (suggestionCount.value > MAX_SUGGESTIONS) list.push(`Au plus ${MAX_SUGGESTIONS} questions suggérées.`)
  return list
})

// Ce qu'on ne peut pas lire n'est ni montré ni touché : l'enregistrement garde ces collections-là telles qu'elles sont.
const hiddenCount = computed(() => props.assistant?.inaccessibleCollectionCount ?? 0)
const instructionsLocked = computed(() => props.assistant?.instructionsHidden ?? false)

function toggleTool(id: string, on: boolean) {
  draft.disabledTools = on ? draft.disabledTools.filter((tool) => tool !== id) : [...new Set([...draft.disabledTools, id])]
}

async function submit() {
  if (problems.value.length) return
  const saved = await saveAssistant(draft, props.assistant?.id)
  if (saved) emit('saved', saved)
}
</script>

<template>
  <form class="assistant-form" @submit.prevent="submit">
    <div class="assistant-form__identity">
      <div class="fr-input-group assistant-form__icon">
        <label class="fr-label" for="assistant-icon">Icône</label>
        <input id="assistant-icon" v-model="draft.icon" class="fr-input" maxlength="4" placeholder="📚" />
      </div>
      <div class="fr-input-group assistant-form__name">
        <label class="fr-label" for="assistant-name">Nom</label>
        <input id="assistant-name" v-model="draft.name" class="fr-input" maxlength="100" required placeholder="RH – congés" />
      </div>
    </div>

    <div class="fr-input-group">
      <label class="fr-label" for="assistant-description">Description</label>
      <input
        id="assistant-description"
        v-model="draft.description"
        class="fr-input"
        maxlength="500"
        placeholder="À quoi sert cet assistant ?"
      />
    </div>

    <div class="fr-input-group">
      <label class="fr-label" for="assistant-instructions">
        Consignes
        <span class="fr-hint-text">
          Rôle, ton, format, langue, règles métier. Elles s’ajoutent aux règles de base de Muffin (réponse tirée des sources,
          citations) sans jamais les remplacer.
        </span>
      </label>
      <p v-if="instructionsLocked" class="assistant-form__hint">
        L’auteur masque les consignes de cet assistant : elles s’appliquent, mais vous ne pouvez pas les lire.
      </p>
      <textarea
        v-else
        id="assistant-instructions"
        v-model="draft.instructions"
        class="fr-input"
        rows="6"
        placeholder="Réponds comme le service RH, uniquement à partir des textes fournis, et cite l’article."
      />
      <p v-if="!instructionsLocked" class="assistant-form__count" :class="{ 'assistant-form__count--over': draft.instructions.length > MAX_INSTRUCTIONS }">
        {{ draft.instructions.length }} / {{ MAX_INSTRUCTIONS }}
      </p>
      <div v-if="!assistant || assistant.isOwner" class="fr-checkbox-group">
        <input id="assistant-hide" v-model="draft.hideInstructions" type="checkbox" />
        <label class="fr-label" for="assistant-hide">
          Masquer les consignes à ceux qui l’utilisent en lecture
          <span class="fr-hint-text">Ils les appliquent sans les voir, et une copie ne les reprend pas.</span>
        </label>
      </div>
    </div>

    <fieldset class="assistant-form__fieldset">
      <legend class="fr-label">Collections</legend>
      <p class="assistant-form__hint">
        L’assistant ne cherche que dans ces collections. Il les <em>désigne</em> : chaque personne n’interroge que celles qu’elle
        peut lire.
      </p>
      <p v-if="hiddenCount" class="assistant-form__hint" role="status">
        {{ hiddenCount }} collection{{ hiddenCount > 1 ? 's' : '' }} de cet assistant ne vous {{ hiddenCount > 1 ? 'sont' : 'est' }} pas
        accessible{{ hiddenCount > 1 ? 's' : '' }} : {{ hiddenCount > 1 ? 'elles sont conservées' : 'elle est conservée' }}, mais vous ne
        la voyez pas.
      </p>
      <ul class="assistant-form__choices">
        <li v-for="collection in collections" :key="collection.id" class="fr-checkbox-group">
          <input :id="`assistant-col-${collection.id}`" v-model="draft.collectionIds" type="checkbox" :value="collection.id" />
          <label class="fr-label" :for="`assistant-col-${collection.id}`">{{ collection.name }}</label>
        </li>
      </ul>
      <p v-if="!collections.length" class="assistant-form__hint">Aucune collection accessible pour l’instant.</p>
      <p v-else-if="!draft.collectionIds.length" class="assistant-form__hint">
        Sans collection, l’assistant cherche dans tout ce que vous pouvez lire, comme le chat habituel.
      </p>
      <div class="fr-checkbox-group">
        <input id="assistant-descendants" v-model="draft.includeDescendants" type="checkbox" />
        <label class="fr-label" for="assistant-descendants">Inclure leurs sous-collections</label>
      </div>
    </fieldset>

    <fieldset class="assistant-form__fieldset">
      <legend class="fr-label">Outils</legend>
      <p class="assistant-form__hint">
        C’est le même agent que dans le chat. Décochez un outil pour que cet assistant ne l’utilise pas ; la recherche dans les
        documents reste toujours active.
      </p>
      <ul class="assistant-form__choices">
        <li v-for="tool in OPTIONAL_TOOLS" :key="tool.id" class="fr-checkbox-group">
          <input
            :id="`assistant-tool-${tool.id}`"
            type="checkbox"
            :checked="!draft.disabledTools.includes(tool.id)"
            @change="toggleTool(tool.id, ($event.target as HTMLInputElement).checked)"
          />
          <label class="fr-label" :for="`assistant-tool-${tool.id}`">
            {{ tool.label }} <span class="fr-hint-text">{{ tool.hint }}</span>
          </label>
        </li>
      </ul>
      <div class="fr-checkbox-group">
        <input id="assistant-web" v-model="draft.webSearchAllowed" type="checkbox" />
        <label class="fr-label" for="assistant-web">
          Autoriser la recherche sur le web
          <span class="fr-hint-text">Jamais activée d’elle-même : l’utilisateur l’allume message par message.</span>
        </label>
      </div>
    </fieldset>

    <div class="fr-input-group">
      <label class="fr-label" for="assistant-suggestions">
        Questions suggérées
        <span class="fr-hint-text">Une par ligne, {{ MAX_SUGGESTIONS }} au plus. Saisies à la main, jamais tirées des documents.</span>
      </label>
      <textarea
        id="assistant-suggestions"
        v-model="draft.suggestions"
        class="fr-input"
        rows="3"
        placeholder="Combien de jours de congé ai-je ?"
      />
    </div>

    <ul v-if="problems.length" class="assistant-form__problems" role="alert">
      <li v-for="problem in problems" :key="problem">{{ problem }}</li>
    </ul>
    <p v-if="assistantError" class="assistant-form__problems" role="alert">{{ assistantError }}</p>

    <div class="assistant-form__actions">
      <button type="submit" class="fr-btn" :disabled="problems.length > 0">
        {{ assistant ? 'Enregistrer' : 'Créer l’assistant' }}
      </button>
      <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
    </div>
  </form>
</template>

<style scoped>
.assistant-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.assistant-form__identity {
  display: flex;
  gap: 0.75rem;
}

.assistant-form__icon {
  width: 5rem;
  flex: none;
}

.assistant-form__name {
  flex: 1;
  min-width: 0;
}

.assistant-form__fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.assistant-form__choices {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 14rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.assistant-form__hint,
.assistant-form__count {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.assistant-form__count--over,
.assistant-form__problems {
  color: var(--text-default-error);
}

.assistant-form__problems {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.875rem;
}

.assistant-form__actions {
  display: flex;
  gap: 0.5rem;
}
</style>
