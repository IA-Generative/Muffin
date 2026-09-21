<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useChat } from '../composables/useChat'
import { useVoiceInput } from '../composables/useVoiceInput'
import type { ChatMessage, FeedbackDetails } from '../types/chat'
import ChatMessageItem from './ChatMessage.vue'
import CollectionPicker from './CollectionPicker.vue'
import DiscussionFeedbackPrompt from './DiscussionFeedbackPrompt.vue'
import ModelSelector from './ModelSelector.vue'

const props = defineProps<{
  messages: ChatMessage[]
}>()

const emit = defineEmits<{
  send: [content: string, collectionIds: string[], webSearchEnabled: boolean]
  regenerate: [id: string]
  feedback: [id: string, value: 'up' | 'down', details?: FeedbackDetails]
  showSources: [id: string]
  showExecution: [id: string]
  showDiscussionScore: []
}>()

const { activeId } = useChat()

const { collections } = useCollections()

const draft = ref('')

const {
  isSupported: voiceSupported,
  isListening: voiceListening,
  error: voiceError,
  start: startVoice,
  stop: stopVoice,
} = useVoiceInput()
// Text already in the composer before this dictation segment started, so a live interim
// result replaces only the in-progress phrase instead of piling up duplicated transcripts.
let voiceBaseDraft = ''

function joinDraft(base: string, addition: string): string {
  if (!addition) return base
  if (!base) return addition
  return /\s$/.test(base) ? base + addition : `${base} ${addition}`
}

function toggleVoice() {
  if (voiceListening.value) {
    stopVoice()
    return
  }
  voiceBaseDraft = draft.value
  startVoice((transcript, isFinal) => {
    draft.value = joinDraft(voiceBaseDraft, transcript)
    if (isFinal) voiceBaseDraft = draft.value
    resizeTextarea()
  })
}

// Global (not just while the textarea has focus) so a keyboard/screen-reader user can start
// dictation from anywhere in the page without first having to tab into the composer - the whole
// point of offering voice input as an accessibility feature in the first place.
function handleGlobalKeydown(event: KeyboardEvent) {
  if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'v') {
    event.preventDefault()
    toggleVoice()
  }
}

onMounted(() => window.addEventListener('keydown', handleGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleGlobalKeydown))

const pinnedCollectionIds = ref<string[]>([])
// Off by default (§ security: never search the web unless explicitly asked - see backend
// RunCreate.web_search_enabled) - stays on across messages once toggled, same as
// pinnedCollectionIds, until the user turns it back off or reloads the page.
const webSearchEnabled = ref(false)
const textarea = ref<HTMLTextAreaElement>()
const scrollAnchor = ref<HTMLElement>()

function submit() {
  const content = draft.value.trim()
  if (!content) return
  emit('send', content, pinnedCollectionIds.value, webSearchEnabled.value)
  draft.value = ''
  resizeTextarea()
}

function unpin(id: string) {
  pinnedCollectionIds.value = pinnedCollectionIds.value.filter((existing) => existing !== id)
}

function resizeTextarea() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  },
)
</script>

<template>
  <section class="chat-window">
    <header class="chat-window__header">
      <ModelSelector />
    </header>

    <div v-if="messages.length === 0" class="chat-window__intro">
      <h1>Qu'est-ce qu'on fait aujourd'hui ?</h1>
    </div>

    <div v-else class="chat-window__messages">
      <div class="chat-window__inner">
        <ChatMessageItem
          v-for="message in messages"
          :key="message.id"
          :message="message"
          @regenerate="emit('regenerate', $event)"
          @feedback="(id, value, details) => emit('feedback', id, value, details)"
          @show-sources="emit('showSources', $event)"
          @show-execution="emit('showExecution', $event)"
        />
        <div ref="scrollAnchor" />
      </div>
    </div>

    <form class="chat-window__form" @submit.prevent="submit">
      <div class="chat-window__inner">
        <DiscussionFeedbackPrompt
          :message-count="messages.length"
          :conversation-id="activeId"
          @open="emit('showDiscussionScore')"
        />
        <ul v-if="pinnedCollectionIds.length > 0" class="chat-window__chips">
          <li v-for="id in pinnedCollectionIds" :key="id" class="chat-window__chip">
            <span>{{ collections.find((collection) => collection.id === id)?.name ?? id }}</span>
            <button type="button" aria-label="Retirer" @click="unpin(id)">
              <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M6.4 5L5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6z"
                />
              </svg>
            </button>
          </li>
        </ul>
        <div class="chat-window__composer">
          <CollectionPicker v-model="pinnedCollectionIds" v-model:web-search-enabled="webSearchEnabled" />
          <textarea
            ref="textarea"
            v-model="draft"
            class="chat-window__textarea"
            placeholder="Écrivez votre message…"
            rows="1"
            @input="resizeTextarea"
            @keydown.enter.exact.prevent="submit"
          />
          <button
            v-if="voiceSupported"
            type="button"
            class="chat-window__mic"
            :class="{ 'chat-window__mic--active': voiceListening }"
            :aria-pressed="voiceListening"
            aria-keyshortcuts="Alt+Shift+V"
            :aria-label="voiceListening ? 'Arrêter la dictée vocale' : 'Dicter le message (raccourci : Alt+Maj+V)'"
            :title="voiceListening ? 'Arrêter la dictée vocale' : 'Dicter le message (Alt+Maj+V)'"
            @click="toggleVoice"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm-6-3a6 6 0 0 0 12 0M12 18v3"
              />
            </svg>
          </button>
          <button
            type="submit"
            class="chat-window__send"
            :disabled="!draft.trim()"
            aria-label="Envoyer"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path fill="currentColor" d="M12 4l7 7h-4v9h-6v-9H5l7-7z" />
            </svg>
          </button>
        </div>
        <p v-if="voiceError" class="chat-window__voice-hint chat-window__voice-hint--error" role="alert">
          {{ voiceError }}
        </p>
        <p v-else-if="!voiceSupported" class="chat-window__voice-hint">
          La dictée vocale n'est pas disponible sur ce navigateur - utilisez Google Chrome ou Microsoft Edge (sur
          ordinateur) pour dicter vos messages.
        </p>
      </div>
    </form>
  </section>
</template>

<style scoped>
.chat-window {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
}

.chat-window__header {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: 0.75rem 1.5rem 0;
}

.chat-window__inner {
  max-width: 48rem;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.chat-window__intro {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0 1.5rem;
}

.chat-window__intro h1 {
  font-size: 1.75rem;
  font-weight: 600;
}

.chat-window__messages {
  flex: 1;
  overflow-y: auto;
  padding-top: 1.5rem;
}

.chat-window__form {
  padding: 0 0 1.5rem;
}

.chat-window__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  list-style: none;
  margin-bottom: 0.5rem;
}

.chat-window__chip {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  border-radius: 1rem;
  border: 1px solid var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
  font-size: 0.75rem;
}

.chat-window__chip button {
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0;
}

.chat-window__composer {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  padding: 0.625rem 0.625rem 0.625rem 1.125rem;
  border-radius: 1.5rem;
  border: 1px solid var(--border-default-grey);
  background: var(--background-default-grey);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.chat-window__textarea {
  flex: 1;
  resize: none;
  border: none;
  background: transparent;
  color: var(--text-default-grey);
  font: inherit;
  line-height: 1.5;
  max-height: 200px;
  padding: 0.375rem 0;
}

.chat-window__textarea:focus {
  outline: none;
}

.chat-window__send {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border: none;
  border-radius: 50%;
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
  cursor: pointer;
}

.chat-window__send:disabled {
  background: var(--background-disabled-grey);
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}

.chat-window__mic {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.chat-window__mic:hover {
  background: var(--background-alt-grey-hover);
  color: var(--text-default-grey);
}

.chat-window__mic--active {
  background: var(--background-error-default);
  color: var(--text-inverted-default);
  animation: chat-window-mic-pulse 1.4s ease-in-out infinite;
}

@keyframes chat-window-mic-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.65;
  }
}

.chat-window__voice-hint {
  margin: 0.5rem 0 0;
  padding: 0 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.chat-window__voice-hint--error {
  color: var(--text-default-error);
}

</style>
