<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMemory } from '../composables/useMemory'
import type { MemoryItem, MemoryKind } from '../types/memory'
import { formatDateTime } from '../utils/routines'

const { memory, isLoading, error, load, add, change, remove, removeAll, setEnabled, exportAll } = useMemory()

const KINDS: { kind: MemoryKind; title: string; hint: string }[] = [
  { kind: 'preference', title: 'Préférences', hint: 'Comment vous aimez les réponses' },
  { kind: 'habit', title: 'Habitudes', hint: 'Ce que vous consultez le plus' },
  { kind: 'context', title: 'Contexte', hint: 'Votre métier, votre service, votre vocabulaire' },
  { kind: 'fact', title: 'Faits', hint: 'Ce que vous avez demandé de retenir' },
]

const newKind = ref<MemoryKind>('preference')
const newValue = ref('')
const editingId = ref<string | null>(null)
const editValue = ref('')
const confirmAll = ref(false)
const message = ref<string | null>(null)
const problem = ref<string | null>(null)

onMounted(load)

const grouped = computed(() =>
  KINDS.map((group) => ({ ...group, items: (memory.value?.items ?? []).filter((item) => item.kind === group.kind) })).filter(
    (group) => group.items.length > 0,
  ),
)

const full = computed(() => !!memory.value && memory.value.items.length >= memory.value.maxItems)

// Un message de retour à la fois : ce qui vient d'être fait, ou ce qui a été refusé.
function done(refused: string | null, ok: string) {
  problem.value = refused
  message.value = refused ? null : ok
}

async function addItem() {
  if (!newValue.value.trim()) return
  const refused = await add(newKind.value, newValue.value.trim())
  if (!refused) newValue.value = ''
  done(refused, 'C’est retenu.')
}

function startEdit(item: MemoryItem) {
  editingId.value = item.id
  editValue.value = item.value
}

async function saveEdit(item: MemoryItem) {
  const refused = await change(item.id, { value: editValue.value.trim() })
  if (!refused) editingId.value = null
  done(refused, 'C’est corrigé : l’élément est désormais le vôtre, rien n’y touchera.')
}

async function toggleItem(item: MemoryItem, enabled: boolean) {
  done(await change(item.id, { enabled }), enabled ? 'Élément réactivé.' : 'Élément désactivé : il n’est plus utilisé.')
}

async function removeItem(item: MemoryItem) {
  done(await remove(item.id), 'Élément supprimé.')
}

async function deleteEverything() {
  confirmAll.value = false
  done(await removeAll(), 'Tout est supprimé.')
}

async function toggleMemory(enabled: boolean) {
  done(await setEnabled(enabled), enabled ? 'La mémoire est activée.' : 'La mémoire est désactivée : rien n’est lu ni retenu.')
}

async function exportMemory() {
  done(await exportAll(), 'Export téléchargé.')
}
</script>

<template>
  <section class="memory-view">
    <div class="memory-view__header">
      <h1>Ma mémoire</h1>
      <button v-if="memory && memory.items.length" type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="exportMemory">
        Exporter (JSON)
      </button>
    </div>
    <p class="memory-view__intro">
      Ce que l’assistant retient de vous pour adapter la <strong>forme</strong> de ses réponses : votre format préféré, votre
      contexte. Ce n’est jamais une source : il ne remplace aucune citation, et ce que vous demandez dans un message passe
      toujours avant. Seul vous le voyez ; vous pouvez tout corriger, désactiver, supprimer ou exporter. Les éléments
      « Appris » viennent de vos 👍 et 👎 (une consigne dite dans un commentaire, plusieurs votes qui concordent) : un seul
      vote ne retient rien, et ce qui n’est plus confirmé disparaît de lui-même.
    </p>

    <p v-if="error" class="memory-view__error" role="alert">{{ error }}</p>
    <p v-else-if="isLoading && !memory" class="memory-view__empty">Chargement…</p>

    <template v-else-if="memory">
      <p v-if="!memory.available" class="fr-alert fr-alert--warning fr-alert--sm memory-view__alert" role="status">
        La mémoire est suspendue sur cette installation : rien n’est lu ni retenu pour l’instant. Ce qui est enregistré reste
        ici.
      </p>

      <div class="memory-card">
        <div class="fr-toggle">
          <input
            id="memory-on"
            type="checkbox"
            class="fr-toggle__input"
            :checked="memory.enabled"
            @change="toggleMemory(($event.target as HTMLInputElement).checked)"
          />
          <label class="fr-toggle__label" for="memory-on" data-fr-checked-label="Activée" data-fr-unchecked-label="Désactivée">
            Activer la mémoire
          </label>
        </div>
        <p class="memory-card__muted">
          Désactivée, l’assistant ne lit ni n’apprend plus rien ; ce qui est ci-dessous reste jusqu’à ce que vous le supprimiez. Pour
          une seule conversation, coupez-la depuis « + » → « Outils » → « Mémoire ».
        </p>
      </div>

      <p v-if="message" class="memory-view__saved" role="status">{{ message }}</p>
      <p v-if="problem" class="memory-view__error" role="alert">{{ problem }}</p>

      <form class="memory-card" @submit.prevent="addItem">
        <h2 class="memory-card__title">Ajouter quelque chose à retenir</h2>
        <div class="memory-card__row">
          <div class="memory-card__field memory-card__field--narrow">
            <label for="memory-kind">Type</label>
            <select id="memory-kind" v-model="newKind" class="fr-select">
              <option v-for="group in KINDS" :key="group.kind" :value="group.kind">{{ group.title }}</option>
            </select>
          </div>
          <div class="memory-card__field">
            <label for="memory-value">Ce qu’il faut retenir</label>
            <input
              id="memory-value"
              v-model="newValue"
              class="fr-input"
              type="text"
              :maxlength="memory.valueMaxChars"
              placeholder="Je préfère des réponses concises, en tableau"
            />
          </div>
        </div>
        <p class="memory-card__muted">
          Rien sur la santé, les opinions, l’origine ou la vie privée n’est retenu, même sur demande. Dans le chat, dites aussi
          « retiens que… », « oublie que… » ou « que sais-tu de moi ? ».
        </p>
        <div class="memory-card__footer">
          <span class="memory-card__muted">{{ memory.items.length }} / {{ memory.maxItems }}</span>
          <button type="submit" class="fr-btn" :disabled="!newValue.trim() || full">Retenir</button>
        </div>
      </form>

      <p v-if="memory.items.length === 0" class="memory-view__empty">L’assistant ne retient rien de vous pour l’instant.</p>

      <div v-for="group in grouped" :key="group.kind" class="memory-card">
        <h2 class="memory-card__title">
          {{ group.title }} <span class="memory-card__muted">— {{ group.hint }}</span>
        </h2>
        <ul class="memory-list">
          <li v-for="item in group.items" :key="item.id" class="memory-row" :class="{ 'memory-row--off': !item.enabled }">
            <div class="memory-row__main">
              <form v-if="editingId === item.id" class="memory-row__edit" @submit.prevent="saveEdit(item)">
                <label class="fr-sr-only" :for="`edit-${item.id}`">Corriger</label>
                <input :id="`edit-${item.id}`" v-model="editValue" class="fr-input" type="text" :maxlength="memory.valueMaxChars" />
                <button type="submit" class="fr-btn fr-btn--sm" :disabled="!editValue.trim()">Enregistrer</button>
                <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="editingId = null">Annuler</button>
              </form>
              <template v-else>
                <p class="memory-row__value">{{ item.value }}</p>
                <p class="memory-row__meta">
                  {{ item.origin === 'explicit' ? 'Écrit par vous' : 'Appris' }} · mis à jour le {{ formatDateTime(item.updatedAt) }}
                  <span v-if="item.lastUsedAt"> · utilisé le {{ formatDateTime(item.lastUsedAt) }}</span>
                  <span v-if="!item.enabled"> · désactivé</span>
                </p>
              </template>
            </div>
            <div v-if="editingId !== item.id" class="memory-row__controls">
              <div class="fr-toggle">
                <input
                  :id="`on-${item.id}`"
                  type="checkbox"
                  class="fr-toggle__input"
                  :checked="item.enabled"
                  @change="toggleItem(item, ($event.target as HTMLInputElement).checked)"
                />
                <label class="fr-toggle__label" :for="`on-${item.id}`" :aria-label="`Utiliser : ${item.value}`">
                  <span class="fr-sr-only">Utiliser</span>
                </label>
              </div>
              <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="startEdit(item)">Corriger</button>
              <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="removeItem(item)">Supprimer</button>
            </div>
          </li>
        </ul>
      </div>

      <div v-if="memory.items.length" class="memory-card">
        <h2 class="memory-card__title">Tout supprimer</h2>
        <template v-if="!confirmAll">
          <p class="memory-card__muted">Supprime définitivement tout ce qui est retenu de vous.</p>
          <div><button type="button" class="fr-btn fr-btn--tertiary" @click="confirmAll = true">Tout supprimer…</button></div>
        </template>
        <template v-else>
          <p class="memory-card__muted">Cela ne peut pas être annulé.</p>
          <div class="memory-card__footer">
            <button type="button" class="fr-btn fr-btn--tertiary" @click="confirmAll = false">Annuler</button>
            <button type="button" class="fr-btn" @click="deleteEverything">Oui, tout supprimer</button>
          </div>
        </template>
      </div>
    </template>
  </section>
</template>

<style scoped>
.memory-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.memory-view__header,
.memory-view__intro,
.memory-view__empty,
.memory-view__error,
.memory-view__saved,
.memory-view__alert {
  max-width: 56rem;
  margin-left: auto;
  margin-right: auto;
}

.memory-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.memory-view__header h1 {
  margin: 0;
}

.memory-view__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.memory-view__empty {
  margin-top: 1rem;
  margin-bottom: 1rem;
  color: var(--text-mention-grey);
}

.memory-view__error {
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
  color: var(--text-default-error);
}

.memory-view__saved {
  margin-top: 0.5rem;
  margin-bottom: 0.5rem;
  color: var(--text-default-success);
}

.memory-view__alert {
  margin-bottom: 1rem;
}

.memory-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-width: 56rem;
  margin: 0 auto 1.25rem;
  padding: 1.25rem 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.memory-card__title {
  margin: 0;
  font-size: 1.0625rem;
}

.memory-card__muted {
  margin: 0;
  font-size: 0.8125rem;
  font-weight: 400;
  color: var(--text-mention-grey);
}

.memory-card__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.memory-card__field {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.375rem;
  min-width: 14rem;
}

.memory-card__field--narrow {
  flex: 0 0 12rem;
  min-width: 10rem;
}

.memory-card__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.memory-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.memory-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-top: 1px solid var(--border-default-grey);
}

.memory-row--off .memory-row__value {
  color: var(--text-mention-grey);
  text-decoration: line-through;
}

.memory-row__main {
  flex: 1;
  min-width: 14rem;
}

.memory-row__value {
  margin: 0;
}

.memory-row__meta {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.memory-row__edit {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.memory-row__edit .fr-input {
  flex: 1;
  min-width: 14rem;
}

.memory-row__controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
</style>
