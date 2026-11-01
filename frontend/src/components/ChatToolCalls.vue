<script setup lang="ts">
import { computed, ref } from 'vue'
import { useChat } from '../composables/useChat'
import type { ChatMessage } from '../types/chat'

const props = defineProps<{ message: ChatMessage }>()

const { decideToolCalls } = useChat()

const calls = computed(() => props.message.toolCalls ?? [])
const waiting = computed(() => calls.value.some((call) => call.status === 'pending'))
const sending = ref(false)
const failed = ref(false)

const STATUS_LABELS: Record<string, string> = {
  pending: 'En attente de votre accord',
  approved: 'Autorisé',
  executed: 'Exécuté',
  failed: 'Autorisé, mais non exécuté',
  refused: 'Refusé : rien n’a été exécuté',
  superseded: 'Abandonné : vous avez écrit autre chose',
  expired: 'Expiré : rien n’a été exécuté',
}

async function decide(approve: boolean) {
  sending.value = true
  failed.value = false
  failed.value = !(await decideToolCalls(props.message.id, approve))
  sending.value = false
}

function shown(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
</script>

<template>
  <section class="tool-calls" :class="{ 'tool-calls--closed': !waiting }" aria-label="Outils qui modifient des données">
    <p class="tool-calls__state">
      {{
        waiting
          ? calls.length === 1
            ? 'L’assistant demande à lancer un outil qui modifie des données. Rien n’a été exécuté.'
            : 'L’assistant demande à lancer des outils qui modifient des données. Rien n’a été exécuté.'
          : 'Outils qui modifient des données'
      }}
    </p>
    <ul class="tool-calls__list">
      <li v-for="call in calls" :key="call.id" class="tool-calls__item">
        <p class="tool-calls__name">
          {{ call.toolName }}<span v-if="call.serverName" class="tool-calls__server"> · {{ call.serverName }}</span>
        </p>
        <dl v-if="Object.keys(call.arguments).length" class="tool-calls__arguments">
          <template v-for="(value, key) in call.arguments" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ shown(value) }}</dd>
          </template>
        </dl>
        <p class="tool-calls__status" :class="{ 'tool-calls__status--pending': call.status === 'pending' }">
          {{ STATUS_LABELS[call.status] ?? call.status }}
        </p>
      </li>
    </ul>
    <div v-if="waiting" class="tool-calls__actions">
      <button type="button" class="fr-btn fr-btn--sm" :disabled="sending" @click="decide(true)">Autoriser</button>
      <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" :disabled="sending" @click="decide(false)">
        Refuser
      </button>
      <p v-if="failed" class="tool-calls__error" role="alert">
        Votre réponse n’a pas pu être prise en compte : la demande a peut-être déjà été traitée ou a expiré.
      </p>
    </div>
  </section>
</template>

<style scoped>
.tool-calls {
  width: 100%;
  max-width: 36rem;
  box-sizing: border-box;
  margin-top: 0.5rem;
  padding: 0.875rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-left: 4px solid var(--border-action-high-warning, var(--border-action-high-blue-france));
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
}

.tool-calls--closed {
  border-left-color: var(--border-default-grey);
}

.tool-calls__state {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.tool-calls__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.tool-calls__item + .tool-calls__item {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-default-grey);
}

.tool-calls__name {
  margin: 0;
  font-weight: 600;
}

.tool-calls__server {
  font-weight: 400;
  color: var(--text-mention-grey);
}

.tool-calls__arguments {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
}

.tool-calls__arguments dt {
  font-weight: 600;
}

.tool-calls__arguments dd {
  margin: 0 0 0.25rem;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.tool-calls__status {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.tool-calls__status--pending {
  color: var(--text-default-warning);
}

.tool-calls__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.tool-calls__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}
</style>
