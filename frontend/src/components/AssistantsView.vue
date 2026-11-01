<script setup lang="ts">
// Les assistants : un réglage nommé (consignes, collections, outils) qu'on choisit en un clic dans le chat, et qu'on partage
// comme une collection (#514).
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAssistants } from '../composables/useAssistants'
import { useAssistantSearch } from '../composables/useAssistantSearch'
import { useCollections } from '../composables/useCollections'
import type { Assistant } from '../types/assistant'
import AssistantForm from './AssistantForm.vue'
import AssistantSharePanel from './AssistantSharePanel.vue'

const router = useRouter()
const { assistants, isLoading, assistantError, select, refreshAssistants, duplicateAssistant, deleteAssistant } = useAssistants()
const { refresh: refreshCollections } = useCollections()

type Panel = { kind: 'edit'; id: string | null } | { kind: 'share'; id: string }
const panel = ref<Panel | null>(null)

onMounted(() => {
  refreshAssistants()
  refreshCollections()
})

const { query, results, active, loading } = useAssistantSearch(computed(() => assistants.value))

const mine = computed(() => results.value.filter((item) => item.isOwner))
const shared = computed(() => results.value.filter((item) => !item.isOwner))
const editing = computed(() =>
  panel.value?.kind === 'edit' && panel.value.id ? (assistants.value.find((item) => item.id === panel.value!.id) ?? null) : null,
)
const sharing = computed(() =>
  panel.value?.kind === 'share' ? (assistants.value.find((item) => item.id === panel.value!.id) ?? null) : null,
)

function use(assistant: Assistant) {
  select(assistant.id)
  router.push('/')
}

async function copy(assistant: Assistant) {
  const created = await duplicateAssistant(assistant.id)
  if (created) panel.value = { kind: 'edit', id: created.id }
}

async function remove(assistant: Assistant) {
  if (!confirm(`Supprimer l’assistant « ${assistant.name} » ? Les personnes avec qui il est partagé ne l’auront plus.`)) return
  if (await deleteAssistant(assistant.id)) panel.value = null
}

function status(assistant: Assistant): string {
  if (!assistant.isOwner) return assistant.canEdit ? 'Partagé avec vous (modifiable)' : 'Partagé avec vous'
  if (assistant.visibility === 'public') return 'Public'
  return assistant.shareCount ? `Partagé (${assistant.shareCount})` : 'Privé'
}
</script>

<template>
  <section class="assistants-view">
    <header class="assistants-view__head">
      <h1>Assistants</h1>
      <button type="button" class="fr-btn" @click="panel = { kind: 'edit', id: null }">Nouvel assistant</button>
    </header>
    <p class="assistants-view__intro">
      Un assistant est un réglage nommé : des <strong>consignes</strong>, des <strong>collections</strong> et des
      <strong>outils</strong>, avec le même agent que dans le chat. On le choisit en un clic dans le chat, et on le partage comme
      une collection. Il ne donne jamais accès à une collection : chacun n’interroge que celles qu’il peut lire.
    </p>
    <p v-if="assistantError && !panel" class="assistants-view__error" role="alert">{{ assistantError }}</p>

    <div v-if="panel?.kind === 'edit'" class="assistants-view__panel">
      <h2>{{ editing ? `Modifier « ${editing.name} »` : 'Nouvel assistant' }}</h2>
      <AssistantForm
        :key="panel.id ?? 'new'"
        :assistant="editing"
        @saved="panel = null"
        @cancel="panel = null"
      />
    </div>

    <div v-else-if="sharing" class="assistants-view__panel">
      <h2>Partager « {{ sharing.name }} »</h2>
      <AssistantSharePanel :assistant="sharing" />
      <button type="button" class="fr-btn fr-btn--secondary" @click="panel = null">Fermer</button>
    </div>

    <template v-else>
      <div v-if="assistants.length > 3" class="assistants-view__search" role="search">
        <label class="fr-label" for="assistants-search">Rechercher un assistant</label>
        <input
          id="assistants-search"
          v-model="query"
          type="search"
          class="fr-input"
          placeholder="Ce qu’il fait : « répond sur les congés », « marchés publics »…"
          autocomplete="off"
        />
        <p v-if="active" class="assistants-view__status" role="status" aria-live="polite">
          {{ loading ? 'Recherche…' : results.length ? `${results.length} résultat${results.length > 1 ? 's' : ''}` : 'Aucun résultat' }}
        </p>
      </div>
      <p v-if="isLoading && !assistants.length" class="assistants-view__empty">Chargement…</p>
      <p v-else-if="!assistants.length" class="assistants-view__empty">
        Aucun assistant pour l’instant. Créez le premier : « RH – congés » avec vos collections de RH et un ton adapté.
      </p>

      <template v-for="group in [{ title: 'Mes assistants', items: mine }, { title: 'Partagés avec moi', items: shared }]" :key="group.title">
        <template v-if="group.items.length">
          <h2>{{ group.title }}</h2>
          <ul class="assistants-view__list">
            <li v-for="assistant in group.items" :key="assistant.id" class="assistants-view__item">
              <span class="assistants-view__icon" aria-hidden="true">{{ assistant.icon || '✨' }}</span>
              <div class="assistants-view__text">
                <strong>{{ assistant.name }}</strong>
                <span v-if="assistant.description" class="assistants-view__description">{{ assistant.description }}</span>
                <span class="assistants-view__meta">
                  {{ status(assistant) }} · {{ assistant.collections.length }} collection{{ assistant.collections.length > 1 ? 's' : '' }} ·
                  version {{ assistant.version }}
                </span>
                <span v-if="assistant.inaccessibleCollectionCount" class="assistants-view__warning" role="status">
                  {{ assistant.inaccessibleCollectionCount }} collection{{ assistant.inaccessibleCollectionCount > 1 ? 's' : '' }} de cet
                  assistant ne vous {{ assistant.inaccessibleCollectionCount > 1 ? 'sont' : 'est' }} pas accessible{{ assistant.inaccessibleCollectionCount > 1 ? 's' : '' }} : ignorée{{ assistant.inaccessibleCollectionCount > 1 ? 's' : '' }}.
                </span>
              </div>
              <div class="assistants-view__actions">
                <button type="button" class="fr-btn fr-btn--sm" @click="use(assistant)">Utiliser</button>
                <button v-if="assistant.canEdit" type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="panel = { kind: 'edit', id: assistant.id }">
                  Modifier
                </button>
                <button v-if="assistant.isOwner" type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="panel = { kind: 'share', id: assistant.id }">
                  Partager
                </button>
                <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="copy(assistant)">Créer ma version</button>
                <button v-if="assistant.isOwner" type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="remove(assistant)">
                  Supprimer
                </button>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </template>
  </section>
</template>

<style scoped>
.assistants-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.assistants-view > * {
  max-width: 52rem;
  margin-left: auto;
  margin-right: auto;
}

.assistants-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.assistants-view__panel {
  margin-top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.assistants-view h2 {
  margin-top: 2rem;
}

.assistants-view__search {
  margin-top: 1rem;
}

.assistants-view__status {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.assistants-view__list {
  list-style: none;
  margin: 0.75rem auto 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.assistants-view__item {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
}

.assistants-view__icon {
  font-size: 1.5rem;
  line-height: 1;
}

.assistants-view__text {
  flex: 1;
  min-width: 12rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.assistants-view__description,
.assistants-view__meta {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.assistants-view__warning {
  font-size: 0.8125rem;
  color: var(--text-default-warning);
}

.assistants-view__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.assistants-view__empty {
  margin-top: 1.5rem;
  color: var(--text-mention-grey);
}

.assistants-view__error {
  color: var(--text-default-error);
}
</style>
