import { computed, ref } from 'vue'
import { router } from '../router'
import type { ChatMessage, Conversation, FeedbackDetails, Source } from '../types/chat'

// Pas encore de backend : réponse Markdown + sources mockées pour valider le rendu de l'UI.
const MOCK_REPLY = `Le **DSFR** (Système de Design de l'État français) fournit des composants, des règles d'accessibilité et une identité visuelle communes à tous les services publics numériques.

Concrètement, ça couvre :
- Les couleurs, typographies et espacements officiels
- Des composants prêts à l'emploi (boutons, formulaires, en-têtes...)
- Des règles d'accessibilité \`RGAA\` intégrées par défaut

Cette réponse est encore mockée : le backend n'est pas branché.`

const MOCK_SOURCES: Source[] = [
  { title: 'systeme-de-design.gouv.fr', url: 'https://www.systeme-de-design.gouv.fr' },
  { title: 'DSFR sur GitHub', url: 'https://github.com/GouvernementFR/dsfr' },
]

function mockAssistantMessage(): ChatMessage {
  return { id: crypto.randomUUID(), role: 'assistant', content: MOCK_REPLY, sources: MOCK_SOURCES }
}

// Module-level singleton, comme useTheme : partagé entre la sidebar (liste des
// conversations) et la zone de chat (messages), sans prop-drilling via App.vue.
const conversations = ref<Conversation[]>([{ id: 'default', title: 'Nouvelle conversation' }])
const activeId = ref('default')
const messagesByConversation = ref<Record<string, ChatMessage[]>>({ default: [] })
const activeSourcesMessageId = ref<string>()

const messages = computed(() => messagesByConversation.value[activeId.value] ?? [])
const activeSources = computed(
  () => messages.value.find((message) => message.id === activeSourcesMessageId.value)?.sources,
)

// `navigate: false` is used when a route change already triggered this (see
// ChatView's route watcher) - pushing again there would just double the entry.
function selectConversation(id: string, options: { navigate?: boolean } = {}) {
  activeId.value = id
  const target = `/c/${id}`
  if (options.navigate !== false && router.currentRoute.value.fullPath !== target) {
    router.push(target)
  }
}

function newConversation() {
  const id = crypto.randomUUID()
  conversations.value.unshift({ id, title: 'Nouvelle conversation' })
  messagesByConversation.value[id] = []
  activeId.value = id
  router.push(`/c/${id}`)
}

function sendMessage(content: string) {
  messagesByConversation.value[activeId.value].push(
    { id: crypto.randomUUID(), role: 'user', content },
    mockAssistantMessage(),
  )
}

function regenerateMessage(id: string) {
  const list = messagesByConversation.value[activeId.value]
  const index = list.findIndex((message) => message.id === id)
  if (index !== -1) list[index] = mockAssistantMessage()
}

function sendFeedback(id: string, value: 'up' | 'down', details?: FeedbackDetails) {
  console.log('Feedback', id, value, details)
}

function showSources(id: string) {
  activeSourcesMessageId.value = id
}

function closeSources() {
  activeSourcesMessageId.value = undefined
}

export function useChat() {
  return {
    conversations,
    activeId,
    messages,
    activeSources,
    selectConversation,
    newConversation,
    sendMessage,
    regenerateMessage,
    sendFeedback,
    showSources,
    closeSources,
  }
}
