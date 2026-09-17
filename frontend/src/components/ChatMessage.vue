<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ChatMessage, FeedbackDetails } from '../types/chat'
import FeedbackModal from './FeedbackModal.vue'

const props = defineProps<{
  message: ChatMessage
}>()

const emit = defineEmits<{
  regenerate: [id: string]
  feedback: [id: string, value: 'up' | 'down', details?: FeedbackDetails]
  showSources: [id: string]
  showExecution: [id: string]
}>()

// User input stays plain text; only the assistant's markdown gets parsed and
// sanitized, since it is the only content that can carry it.
const renderedContent = computed(() =>
  props.message.role === 'assistant'
    ? DOMPurify.sanitize(marked.parse(props.message.content, { async: false }))
    : props.message.content,
)

const copied = ref(false)
const feedback = ref<'up' | 'down' | null>(null)
const showMenu = ref(false)
const showFeedbackModal = ref(false)
const menuWrapper = ref<HTMLElement>()
let copiedTimeout: ReturnType<typeof setTimeout> | undefined

function handleOutsideClick(event: MouseEvent) {
  if (showMenu.value && !menuWrapper.value?.contains(event.target as Node)) {
    showMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', handleOutsideClick))

async function copyContent() {
  await navigator.clipboard.writeText(props.message.content)
  copied.value = true
  clearTimeout(copiedTimeout)
  copiedTimeout = setTimeout(() => (copied.value = false), 1500)
}

function thumbUp() {
  feedback.value = feedback.value === 'up' ? null : 'up'
  if (feedback.value === 'up') emit('feedback', props.message.id, 'up')
}

function thumbDown() {
  if (feedback.value === 'down') {
    feedback.value = null
    return
  }
  showFeedbackModal.value = true
}

function submitFeedback(details: FeedbackDetails) {
  feedback.value = 'down'
  showFeedbackModal.value = false
  emit('feedback', props.message.id, 'down', details)
}

function openSources() {
  showMenu.value = false
  emit('showSources', props.message.id)
}

function openExecutionDetails() {
  showMenu.value = false
  emit('showExecution', props.message.id)
}

const sourcesLabel = computed(() => {
  const sources = props.message.sources
  if (!sources?.length) return undefined
  const [first, ...rest] = sources
  try {
    const domain = new URL(first.url).hostname.replace(/^www\./, '')
    return rest.length ? `${domain} +${rest.length}` : domain
  } catch {
    return rest.length ? `${first.title} +${rest.length}` : first.title
  }
})

onBeforeUnmount(() => {
  clearTimeout(copiedTimeout)
  document.removeEventListener('click', handleOutsideClick)
})
</script>

<template>
  <div class="chat-message" :class="`chat-message--${message.role}`">
    <div class="chat-message__bubble">
      <p v-if="message.role === 'user'" class="chat-message__text">{{ renderedContent }}</p>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div v-else class="chat-message__markdown" v-html="renderedContent" />

      <button
        v-if="sourcesLabel"
        type="button"
        class="chat-message__sources-chip"
        @click="openSources"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244" />
        </svg>
        {{ sourcesLabel }}
      </button>

      <div v-if="message.role === 'assistant'" class="chat-message__actions">
        <button type="button" class="chat-message__action" title="Copier" @click="copyContent">
          <svg
            v-if="!copied"
            viewBox="0 0 24 24"
            width="17"
            height="17"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            aria-hidden="true"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
            />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
          </svg>
        </button>

        <button
          type="button"
          class="chat-message__action"
          :class="{ 'chat-message__action--active': feedback === 'up' }"
          title="Bonne réponse"
          @click="thumbUp"
        >
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M6.633 10.5c.806 0 1.533-.422 2.031-1.08a9.041 9.041 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V3a.75.75 0 0 1 .75-.75A2.25 2.25 0 0 1 16.5 4.5c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.423-.23H5.904M14.25 9h2.25M5.904 18.75c.083.205.173.405.27.602.197.4-.078.898-.523.898h-.908c-.889 0-1.713-.518-1.972-1.368a12 12 0 0 1-.521-3.507c0-1.553.295-3.036.831-4.398C3.387 10.203 4.167 9.75 5 9.75h1.053c.472 0 .745.556.5.96a8.958 8.958 0 0 0-1.302 4.665c0 1.194.232 2.333.654 3.375z"
            />
          </svg>
        </button>

        <button
          type="button"
          class="chat-message__action"
          :class="{ 'chat-message__action--active': feedback === 'down' }"
          title="Mauvaise réponse"
          @click="thumbDown"
        >
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M7.5 15h2.25m8.024-9.75c.011.05.028.1.052.148.591 1.2.924 2.55.924 3.977a8.96 8.96 0 0 1-.999 4.125m.023-8.25c-.076-.365.183-.75.575-.75h.908c.889 0 1.713.518 1.972 1.368.339 1.11.521 2.287.521 3.507 0 1.553-.295 3.036-.831 4.398C20.613 14.547 19.833 15 19 15h-1.053c-.472 0-.745-.556-.5-.96a8.95 8.95 0 0 0 .303-.54m.023-8.25H16.48a4.5 4.5 0 0 1-1.423-.23l-3.114-1.04a4.5 4.5 0 0 0-1.423-.23H6.504c-.618 0-1.217.247-1.605.729A11.95 11.95 0 0 0 2.25 12c0 .434.023.863.068 1.285C2.427 14.306 3.346 15 4.372 15h3.126c.618 0 .991.724.725 1.282A7.471 7.471 0 0 0 7.5 19.5v1.25c0 .414.336.75.75.75a2.25 2.25 0 0 0 2.25-2.25v-.63c0-.55.108-1.093.322-1.586.25-.575.687-1.043 1.212-1.38a8.988 8.988 0 0 0 2.62-2.652v-1.5"
            />
          </svg>
        </button>

        <button
          type="button"
          class="chat-message__action"
          title="Régénérer"
          @click="emit('regenerate', message.id)"
        >
          <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
            />
          </svg>
        </button>

        <div ref="menuWrapper" class="chat-message__menu-wrapper">
          <button
            type="button"
            class="chat-message__action"
            title="Plus d'options"
            @click="showMenu = !showMenu"
          >
            <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
              <circle cx="5" cy="12" r="1.75" fill="currentColor" />
              <circle cx="12" cy="12" r="1.75" fill="currentColor" />
              <circle cx="19" cy="12" r="1.75" fill="currentColor" />
            </svg>
          </button>

          <div v-if="showMenu" class="chat-message__menu" role="menu">
            <button
              type="button"
              class="chat-message__menu-item"
              role="menuitem"
              :disabled="!message.sources?.length"
              @click="openSources"
            >
              Afficher les sources
            </button>
            <button
              type="button"
              class="chat-message__menu-item"
              role="menuitem"
              :disabled="!message.runId"
              @click="openExecutionDetails"
            >
              Détail de l'exécution
            </button>
          </div>
        </div>
      </div>
    </div>

    <FeedbackModal
      v-if="showFeedbackModal"
      :sources="message.sources"
      @close="showFeedbackModal = false"
      @submit="submitFeedback"
    />
  </div>
</template>

<style scoped>
.chat-message {
  display: flex;
  padding: 0.5rem 0;
}

.chat-message--user {
  justify-content: flex-end;
}

.chat-message--assistant {
  justify-content: flex-start;
}

.chat-message__text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}

.chat-message--user .chat-message__bubble {
  max-width: 75%;
  padding: 0.75rem 1.125rem;
  border-radius: 1.25rem;
  background: var(--background-alt-grey);
}

.chat-message--assistant .chat-message__bubble {
  max-width: 100%;
}

.chat-message__markdown {
  line-height: 1.6;
}

.chat-message__markdown :first-child {
  margin-top: 0;
}

.chat-message__markdown :last-child {
  margin-bottom: 0;
}

.chat-message__markdown pre {
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
  overflow-x: auto;
}

.chat-message__markdown code {
  font-family: 'Consolas', monospace;
  background: var(--background-alt-grey);
  border-radius: 0.25rem;
  padding: 0.1rem 0.3rem;
}

.chat-message__markdown pre code {
  background: none;
  padding: 0;
}

.chat-message__sources-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  margin-top: 0.625rem;
  padding: 0.3rem 0.75rem;
  border-radius: 1rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
  font-size: 0.8125rem;
  cursor: pointer;
}

.chat-message__sources-chip:hover {
  background: var(--background-alt-grey-hover);
}

.chat-message__actions {
  display: flex;
  align-items: center;
  gap: 0.125rem;
  margin-top: 0.5rem;
}

.chat-message__action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.chat-message__action:hover {
  background: var(--background-alt-grey-hover);
  color: var(--text-default-grey);
}

.chat-message__action--active {
  color: var(--text-action-high-blue-france);
}

.chat-message__menu-wrapper {
  position: relative;
}

.chat-message__menu {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 0.25rem;
  padding: 0.25rem;
  min-width: 12rem;
  background: var(--background-default-grey);
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 10;
}

.chat-message__menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.75rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
}

.chat-message__menu-item:hover {
  background: var(--background-alt-grey-hover);
}

.chat-message__menu-item:disabled {
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}
</style>
