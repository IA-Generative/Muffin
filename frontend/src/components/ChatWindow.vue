<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import { useChat } from '../composables/useChat'
import { useAssistants } from '../composables/useAssistants'
import { type QaSuggestion, useQaSuggestions } from '../composables/useQaSuggestions'
import { type CollectionImport, isZip, useCollectionImports } from '../composables/useCollectionImports'
import { useFiling } from '../composables/useFiling'
import { useImageGeneration } from '../composables/useImageGeneration'
import { useImageAttachments } from '../composables/useImageAttachments'
import { imagesOf } from '../utils/imageResize'
import { useVoiceInput } from '../composables/useVoiceInput'
import { useVoiceOutput } from '../composables/useVoiceOutput'
import type { ChatMessage, ConversationFile, FeedbackDetails } from '../types/chat'
import type { StagedImage } from '../composables/useImageAttachments'
import { toPlainText } from '../utils/plainText'
import ChatMessageItem from './ChatMessage.vue'
import CollectionPicker from './CollectionPicker.vue'
import DiscussionFeedbackPrompt from './DiscussionFeedbackPrompt.vue'
import FileFilingModal from './FileFilingModal.vue'
import AssistantSelector from './AssistantSelector.vue'
import ConversationTools from './ConversationTools.vue'
import ModelSelector from './ModelSelector.vue'

const props = defineProps<{
  messages: ChatMessage[]
}>()

const emit = defineEmits<{
  send: [
    content: string,
    collectionIds: string[],
    webSearchEnabled: boolean,
    includeDescendants: boolean,
    images: StagedImage[],
  ]
  generateImage: [prompt: string, images: StagedImage[]]
  askSuggestion: [suggestion: QaSuggestion]
  regenerate: [id: string]
  feedback: [id: string, value: 'up' | 'down', details?: FeedbackDetails]
  showSources: [id: string]
  showExecution: [id: string]
  showDiscussionScore: []
}>()

const {
  activeId,
  focusedMessageId,
  activeAttachedFiles,
  attachFile,
  removeAttachedFile,
  markAttachedFileDismissed,
  dropAttachedFileLocally,
  attachZip,
  activeImports,
} = useChat()
const { decideAttachment } = useCollectionImports()

const { collections } = useCollections()
const { decideFiling } = useFiling()

const fileInput = ref<HTMLInputElement>()

function openFilePicker() {
  fileInput.value?.click()
}

function handleFilesSelected(event: Event) {
  const target = event.target as HTMLInputElement
  // A ZIP becomes a collection of its own, pinned to this conversation (#223) - not a conversation file.
  if (target.files)
    for (const file of target.files) {
      if (isZip(file)) attachZip(activeId.value, file)
      else attachFile(activeId.value, file)
    }
  target.value = '' // lets the same file be re-selected later
}

const FILE_STATUS_ICON: Record<string, string> = {
  queued: '⏳',
  pending: '⏳',
  indexing: '⏳',
  indexed: '✅',
  error: '❌',
}

// A file has something to say once it's indexed and not yet dismissed - either a suggested
// collection to review, or (no match found) still worth prompting the user to pick one
// themselves, per #122.
function hasFilingNotification(file: ConversationFile): boolean {
  return file.status === 'indexed' && !file.filingDismissed
}

const filingModalFile = ref<ConversationFile>()

async function decideFilingFor(action: 'accept' | 'choose_other' | 'dismiss', targetCollectionId?: string) {
  const file = filingModalFile.value
  if (!file) return
  try {
    await decideFiling(file.id, action, targetCollectionId)
    if (action === 'dismiss') markAttachedFileDismissed(activeId.value, file.id)
    else dropAttachedFileLocally(activeId.value, file.id)
    filingModalFile.value = undefined
  } catch {
    // The modal itself shows nothing on failure today (best-effort chip list, same tradeoff as
    // the rest of the composer) - closing it still leaves the notification for a retry.
    filingModalFile.value = undefined
  }
}

const IMPORT_STATUS_ICON: Record<CollectionImport['status'], string> = {
  queued: '⏳',
  uploading: '⏳',
  pending: '⏳',
  running: '⏳',
  completed: '🗂️',
  failed: '❌',
  upload_failed: '❌',
}

function importTitle(item: CollectionImport): string {
  if (item.status === 'queued') return 'Sera importée avec votre message'
  if (item.error) return item.error
  if (item.status !== 'completed' || !item.summary) return 'Import en cours'
  const skipped = item.summary.skipped.length ? `, ${item.summary.skipped.length} fichier(s) ignoré(s)` : ''
  return `${item.summary.collectionsCreated} sous-collection(s), ${item.summary.documentsCreated} document(s)${skipped}`
}

// The collection of a ZIP dropped here waits for an answer about where to attach it, once the
// pipeline has described it well enough to suggest somewhere (#223).
function hasAttachNotification(item: CollectionImport): boolean {
  return item.attachStatus === 'pending' && item.attachCandidates.length > 0
}

const attachModalImport = ref<CollectionImport>()

async function decideAttachmentFor(action: 'accept' | 'choose_other' | 'dismiss', targetCollectionId?: string) {
  const item = attachModalImport.value
  if (!item) return
  try {
    await decideAttachment(item.id, action, targetCollectionId)
  } catch {
    // Same tradeoff as decideFilingFor: closing still leaves the notification for a retry.
  }
  attachModalImport.value = undefined
}

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

const voiceOutput = useVoiceOutput()

// Only the answer that closes the thread may offer to "go further" (#219): the backend resumes
// from the previous answer of the conversation, so an older one would resume from the wrong place.
const latestAnswerId = computed(() => {
  const last = props.messages[props.messages.length - 1]
  return last?.role === 'assistant' && !last.pending ? last.id : undefined
})

// Reads the most recent completed assistant answer aloud (or stops it if already reading it) -
// a pending/error bubble has nothing worth reading yet, so those are skipped.
function toggleReadLastMessage() {
  const lastAnswer = [...props.messages].reverse().find((m) => m.role === 'assistant' && !m.pending && !m.error)
  if (!lastAnswer) return
  voiceOutput.toggle(lastAnswer.id, toPlainText(lastAnswer.content))
}

// Global (not just while the textarea has focus) so a keyboard/screen-reader user can start
// dictation/reading from anywhere in the page without first having to tab into the composer -
// the whole point of offering voice input/output as an accessibility feature in the first place.
function handleGlobalKeydown(event: KeyboardEvent) {
  if (!event.altKey || !event.shiftKey) return
  const key = event.key.toLowerCase()
  if (key === 'v') {
    event.preventDefault()
    toggleVoice()
  } else if (key === 'l') {
    event.preventDefault()
    toggleReadLastMessage()
  }
}

onMounted(() => window.addEventListener('keydown', handleGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleGlobalKeydown))

// The mode «Image» (#518): the next message is the description of an image, not a question. Offered only when the
// function is on and this person may use it; explicit, and off again once it stops being available. Never chosen by
// the model.
const { imageStatus, loadImageStatus } = useImageGeneration()
const imageMode = ref(false)
onMounted(loadImageStatus)
watch(
  () => imageStatus.value.available,
  (available) => {
    if (!available) imageMode.value = false
  },
)
const imageQuotaLabel = computed(() => {
  const left = imageStatus.value.remainingToday
  if (left === null) return ''
  return left === 0 ? 'Plus aucune image aujourd’hui.' : `${left} image${left > 1 ? 's' : ''} restante${left > 1 ? 's' : ''} aujourd’hui.`
})

const pinnedCollectionIds = ref<string[]>([])
// Off by default (§ security: never search the web unless explicitly asked - see backend
// RunCreate.web_search_enabled) - stays on across messages once toggled, same as
// pinnedCollectionIds, until the user turns it back off or reloads the page.
const webSearchEnabled = ref(false)
// Attaching a collection brings its sub-collections along unless unchecked (#220).
const includeDescendants = ref(true)
const textarea = ref<HTMLTextAreaElement>()
const { suggestions, loadSuggestions } = useQaSuggestions()
const { selectedAssistant } = useAssistants()

// Drawn again each time the chat is empty - a new conversation, or another set of pinned
// collections - so the starter questions vary and follow what the user is about to search.
watch(
  () => [props.messages.length === 0, activeId.value, pinnedCollectionIds.value.join(','), selectedAssistant.value?.id] as const,
  ([isEmpty]) => {
    // With an assistant the starter questions are its own, typed by hand: none are drawn from the collections.
    if (isEmpty && !selectedAssistant.value) loadSuggestions(pinnedCollectionIds.value)
  },
  { immediate: true },
)
const scrollAnchor = ref<HTMLElement>()

// The images chosen for the message (#512): a thumbnail at once, the upload behind it. A message goes out once they are all
// kept; with images and nothing written, the question is the obvious one.
const { attachmentStatus, staged, uploading, loadAttachmentStatus, addImages, removeStagedImage, takeStagedImages } =
  useImageAttachments()
const imageInput = ref<HTMLInputElement>()
onMounted(loadAttachmentStatus)
const imageButtonTitle = computed(() =>
  attachmentStatus.value.available
    ? 'Joindre une image : le modèle la lira pour répondre'
    : 'Aucun modèle capable de lire les images n’est disponible : les images ne peuvent pas être jointes.',
)

function handleImagesSelected(event: Event) {
  const target = event.target as HTMLInputElement
  addImages(target.files)
  target.value = '' // lets the same image be chosen again
}

// An image pasted into the message (a screenshot, say) is attached; any other paste is left as it is.
function handlePaste(event: ClipboardEvent) {
  const images = imagesOf(event.clipboardData?.files)
  if (!images.length || !attachmentStatus.value.available) return
  event.preventDefault()
  addImages(images)
}

// Files dropped on the composer: images go with the message when a model reads them, anything else is attached as a file,
// a ZIP as a collection, as with the paperclip.
function handleDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files ?? [])
  for (const file of files) {
    if (attachmentStatus.value.available && imagesOf([file]).length) addImages([file])
    else if (isZip(file)) attachZip(activeId.value, file)
    else attachFile(activeId.value, file)
  }
}

function submit() {
  if (uploading.value) return
  const ready = staged.value.some((image) => image.status === 'ready')
  const content = draft.value.trim() || (ready && !imageMode.value ? 'Que montre cette image ?' : '')
  if (!content) return
  if (imageMode.value && imageStatus.value.available) {
    emit('generateImage', content, takeStagedImages())
  } else {
    emit('send', content, pinnedCollectionIds.value, webSearchEnabled.value, includeDescendants.value, takeStagedImages())
  }
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

// The message a search result led to (#509): the conversation opens on it rather than at its end, and the message is
// outlined for a moment. It only counts once the messages are there, and is forgotten when found.
const foundMessageId = ref<string | null>(null)
let foundTimer: ReturnType<typeof setTimeout> | undefined

watch(
  () => [focusedMessageId.value, props.messages.length] as const,
  async ([id]) => {
    if (!id || !props.messages.some((message) => message.id === id)) return
    // Marked before it is forgotten: the watch below, fired by the same change, must still see that the end of the
    // conversation is not where to go.
    foundMessageId.value = id
    focusedMessageId.value = null
    clearTimeout(foundTimer)
    foundTimer = setTimeout(() => (foundMessageId.value = null), 2500)
    await nextTick()
    document.querySelector(`[data-message-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  },
  { immediate: true },
)
onUnmounted(() => clearTimeout(foundTimer))

watch(
  () => props.messages.length,
  async () => {
    // Opening a conversation on a message found by the search must not be followed by a jump to its end.
    if (focusedMessageId.value || foundMessageId.value) return
    await nextTick()
    scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  },
)
</script>

<template>
  <section class="chat-window">
    <header class="chat-window__header">
      <AssistantSelector />
      <ConversationTools />
      <ModelSelector />
    </header>

    <div v-if="messages.length === 0" class="chat-window__intro">
      <div class="chat-window__welcome">
        <template v-if="selectedAssistant">
          <h1>
            <span aria-hidden="true">{{ selectedAssistant.icon || '✨' }}</span> {{ selectedAssistant.name }}
          </h1>
          <p v-if="selectedAssistant.description" class="chat-window__assistant-description">
            {{ selectedAssistant.description }}
          </p>
          <p v-if="selectedAssistant.inaccessibleCollectionCount" class="chat-window__assistant-warning" role="status">
            {{ selectedAssistant.inaccessibleCollectionCount }} collection{{
              selectedAssistant.inaccessibleCollectionCount > 1 ? 's' : ''
            }}
            de cet assistant ne vous {{ selectedAssistant.inaccessibleCollectionCount > 1 ? 'sont' : 'est' }} pas accessible{{
              selectedAssistant.inaccessibleCollectionCount > 1 ? 's' : ''
            }}
            : {{ selectedAssistant.inaccessibleCollectionCount > 1 ? 'elles sont ignorées' : 'elle est ignorée' }}.
          </p>
          <ul v-if="selectedAssistant.suggestions.length" class="chat-window__suggestions" aria-label="Questions suggérées">
            <li v-for="question in selectedAssistant.suggestions" :key="question">
              <button type="button" class="chat-window__suggestion" @click="emit('send', question, [], webSearchEnabled, true, [])">
                <span class="chat-window__suggestion-question">{{ question }}</span>
              </button>
            </li>
          </ul>
        </template>
        <h1 v-else>Qu'est-ce qu'on fait aujourd'hui ?</h1>
        <ul v-if="!selectedAssistant && suggestions.length" class="chat-window__suggestions" aria-label="Questions suggérées">
          <li v-for="suggestion in suggestions" :key="suggestion.id">
            <button type="button" class="chat-window__suggestion" @click="emit('askSuggestion', suggestion)">
              <span class="chat-window__suggestion-question">{{ suggestion.question }}</span>
              <span class="chat-window__suggestion-collection">{{ suggestion.collectionName }}</span>
            </button>
          </li>
        </ul>
      </div>
    </div>

    <div v-else class="chat-window__messages">
      <div class="chat-window__inner">
        <ChatMessageItem
          v-for="message in messages"
          :key="message.id"
          :data-message-id="message.id"
          :class="{ 'chat-window__message--found': message.id === foundMessageId }"
          :message="message"
          :is-latest-answer="message.id === latestAnswerId"
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
        <ul v-if="activeAttachedFiles.length > 0" class="chat-window__chips">
          <li
            v-for="file in activeAttachedFiles"
            :key="file.id"
            class="chat-window__chip"
            :class="{ 'chat-window__chip--error': file.status === 'error' }"
            :title="file.status === 'queued' ? 'Sera envoyé avec votre message' : file.name"
          >
            <span aria-hidden="true">{{ FILE_STATUS_ICON[file.status] }}</span>
            <span>{{ file.name }}</span>
            <button
              v-if="hasFilingNotification(file)"
              type="button"
              class="chat-window__chip-notification"
              :aria-label="`Proposition de rangement pour ${file.name}`"
              title="Proposition de rangement"
              @click="filingModalFile = file"
            >
              <span aria-hidden="true">📁</span>
            </button>
            <button type="button" aria-label="Retirer ce fichier" @click="removeAttachedFile(activeId, file.id)">
              <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
                <path
                  fill="currentColor"
                  d="M6.4 5L5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6z"
                />
              </svg>
            </button>
          </li>
        </ul>
        <ul v-if="activeImports.length > 0" class="chat-window__chips">
          <li
            v-for="item in activeImports"
            :key="item.id"
            class="chat-window__chip"
            :class="{ 'chat-window__chip--error': item.status === 'failed' || item.status === 'upload_failed' }"
            :title="importTitle(item)"
          >
            <span aria-hidden="true">{{ IMPORT_STATUS_ICON[item.status] }}</span>
            <span>{{ item.rootCollectionName ?? item.archiveName }}</span>
            <button
              v-if="hasAttachNotification(item)"
              type="button"
              class="chat-window__chip-notification"
              :aria-label="`Proposition de rattachement pour ${item.rootCollectionName ?? item.archiveName}`"
              title="Proposition de rattachement"
              @click="attachModalImport = item"
            >
              <span aria-hidden="true">📁</span>
            </button>
          </li>
        </ul>
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
        <p v-if="imageMode" class="chat-window__image-hint" role="status">
          <template v-if="staged.length">
            Mode image : votre message décrit la retouche à faire sur les images jointes. Elles et votre message sont
            envoyés au fournisseur d’images choisi par l’administrateur, et l’image est étiquetée « générée par IA ».
          </template>
          <template v-else>
            Mode image : votre message décrit l’image à créer. Il est envoyé au fournisseur d’images choisi par
            l’administrateur, et l’image est étiquetée « générée par IA ».
          </template>
          {{ imageQuotaLabel }}
        </p>
        <ul v-if="staged.length" class="chat-window__staged" aria-label="Images jointes au message">
          <li v-for="(image, index) in staged" :key="image.tempId" class="chat-window__staged-item">
            <img :src="image.previewUrl" :alt="`Aperçu de l’image jointe ${index + 1}`" class="chat-window__staged-image" />
            <span v-if="image.status === 'uploading'" class="chat-window__staged-state" role="status">Envoi…</span>
            <span v-else-if="image.status === 'error'" class="chat-window__staged-state chat-window__staged-state--error" role="alert">
              {{ image.message }}
            </span>
            <button type="button" class="chat-window__staged-remove" :aria-label="`Retirer l’image jointe ${index + 1}`" @click="removeStagedImage(image.tempId)">
              ✕
            </button>
          </li>
        </ul>
        <div class="chat-window__composer" @dragover.prevent @drop.prevent="handleDrop">
          <CollectionPicker
            v-if="!selectedAssistant"
            v-model="pinnedCollectionIds"
            v-model:web-search-enabled="webSearchEnabled"
            v-model:include-descendants="includeDescendants"
          />
          <label v-else-if="selectedAssistant.webSearchAllowed" class="chat-window__assistant-web">
            <input v-model="webSearchEnabled" type="checkbox" />
            Web
          </label>
          <input
            ref="fileInput"
            type="file"
            multiple
            class="chat-window__file-input"
            aria-label="Choisir des fichiers à joindre"
            @change="handleFilesSelected"
          />
          <button
            type="button"
            class="chat-window__attach"
            aria-label="Joindre des fichiers"
            title="Joindre des fichiers"
            @click="openFilePicker"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M17.5 8.5 9.62 16.38a3 3 0 0 1-4.24-4.24l8.13-8.13a2 2 0 0 1 2.83 2.83l-7.78 7.78a1 1 0 0 1-1.41-1.41l7.07-7.07"
              />
            </svg>
          </button>
          <input
            ref="imageInput"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            class="chat-window__file-input"
            aria-label="Choisir des images à joindre au message"
            @change="handleImagesSelected"
          />
          <button
            type="button"
            class="chat-window__attach"
            :disabled="!attachmentStatus.available || staged.length >= attachmentStatus.maxImages"
            aria-label="Joindre une image"
            :title="imageButtonTitle"
            @click="imageInput?.click()"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M2.25 15.75 7.41 10.59a2.25 2.25 0 0 1 3.18 0l5.16 5.16m-1.5-1.5 1.41-1.41a2.25 2.25 0 0 1 3.18 0l2.41 2.41M18 7.5h.01M3.75 19.5h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z"
              />
            </svg>
          </button>
          <button
            v-if="imageStatus.available"
            type="button"
            class="chat-window__attach"
            :class="{ 'chat-window__image--active': imageMode }"
            :aria-pressed="imageMode"
            aria-label="Générer une image"
            title="Générer une image : votre message décrit l’image à créer"
            @click="imageMode = !imageMode"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="m2.25 15.75 5.16-5.16a2.25 2.25 0 0 1 3.18 0l5.16 5.16m-1.5-1.5 1.41-1.41a2.25 2.25 0 0 1 3.18 0l2.41 2.41m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Zm10.5-11.25h.01v.01h-.01V8.25Z"
              />
            </svg>
          </button>
          <textarea
            ref="textarea"
            v-model="draft"
            class="chat-window__textarea"
            :placeholder="imageMode ? 'Décrivez l’image à générer…' : 'Écrivez votre message…'"
            :maxlength="imageMode ? (imageStatus.maxPromptChars ?? undefined) : undefined"
            rows="1"
            @input="resizeTextarea"
            @paste="handlePaste"
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
            :disabled="uploading || (!draft.trim() && !(staged.some((image) => image.status === 'ready') && !imageMode))"
            :title="uploading ? 'Les images sont en cours d’envoi…' : undefined"
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

    <FileFilingModal
      v-if="attachModalImport"
      :file="{
        name: attachModalImport.rootCollectionName ?? attachModalImport.archiveName,
        suggestedCollectionId: attachModalImport.attachCandidates[0]?.collectionId,
        filingCandidates: attachModalImport.attachCandidates,
      }"
      :title="`Rattacher « ${attachModalImport.rootCollectionName ?? attachModalImport.archiveName} » à une collection`"
      owned-only
      :exclude-collection-ids="attachModalImport.rootCollectionId ? [attachModalImport.rootCollectionId] : []"
      :allow-create="false"
      @close="attachModalImport = undefined"
      @decide="decideAttachmentFor"
    />
    <FileFilingModal
      v-if="filingModalFile"
      :file="filingModalFile"
      @close="filingModalFile = undefined"
      @decide="decideFilingFor"
    />
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

.chat-window__assistant-description {
  margin: 0;
  color: var(--text-mention-grey);
}

.chat-window__assistant-warning {
  margin: 0.5rem 0 0;
  font-size: 0.875rem;
  color: var(--text-default-warning);
}

.chat-window__assistant-web {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.chat-window__header {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
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

.chat-window__welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.5rem;
  max-width: 40rem;
  width: 100%;
}

.chat-window__suggestions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;
}

.chat-window__suggestion {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  text-align: left;
  cursor: pointer;
}

.chat-window__suggestion:hover {
  background: var(--background-default-grey-hover);
}

.chat-window__suggestion-question {
  font-size: 0.9375rem;
}

.chat-window__suggestion-collection {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.chat-window__messages {
  flex: 1;
  overflow-y: auto;
  padding-top: 1.5rem;
}

.chat-window__form {
  padding: 0 0 1.5rem;
}

/* The message a search result led to, outlined for a moment (#509). */
.chat-window__message--found {
  outline: 2px solid var(--border-action-high-blue-france);
  outline-offset: 4px;
  border-radius: 0.5rem;
}

.chat-window__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  list-style: none;
  margin-bottom: 0.5rem;
}

.chat-window__staged {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0 0 0.5rem;
  padding: 0;
  list-style: none;
}

.chat-window__staged-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.125rem;
}

.chat-window__staged-image {
  display: block;
  width: 4.5rem;
  height: 4.5rem;
  object-fit: cover;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.chat-window__staged-state {
  max-width: 6rem;
  font-size: 0.6875rem;
  color: var(--text-mention-grey);
  text-align: center;
}

.chat-window__staged-state--error {
  color: var(--text-default-error);
}

.chat-window__staged-remove {
  position: absolute;
  top: -0.375rem;
  right: -0.375rem;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  border: 1px solid var(--border-default-grey);
  border-radius: 50%;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.6875rem;
  line-height: 1;
  cursor: pointer;
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

.chat-window__chip--error {
  border-color: var(--border-plain-error);
  background: var(--background-contrast-error);
  color: var(--text-default-error);
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

.chat-window__chip-notification {
  font-size: 0.75rem;
  animation: chat-window-notification-pulse 1.8s ease-in-out infinite;
}

@keyframes chat-window-notification-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
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

.chat-window__file-input {
  display: none;
}

.chat-window__attach {
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

.chat-window__attach:hover {
  background: var(--background-alt-grey-hover);
  color: var(--text-default-grey);
}

.chat-window__image--active {
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
}

.chat-window__image-hint {
  margin: 0 0 0.375rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
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
