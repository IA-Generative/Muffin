<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChat } from '../composables/useChat'
import ChatWindow from './ChatWindow.vue'
import DiscussionScorePanel from './DiscussionScorePanel.vue'
import ExecutionPanel from './ExecutionPanel.vue'
import SourcesPanel from './SourcesPanel.vue'

const route = useRoute()
const router = useRouter()

const {
  activeId,
  messages,
  activeSources,
  activeExecutionMessageId,
  activeExecutionEvents,
  activeExecutionError,
  selectConversation,
  sendMessage,
  regenerateMessage,
  sendFeedback,
  showSources,
  closeSources,
  showExecutionDetails,
  closeExecutionDetails,
} = useChat()

const showDiscussionPanel = ref(false)

// "/" has no conversation id: normalize it to the active one so the URL
// always reflects which conversation is open, without adding a history entry.
watch(
  () => route.params.id,
  (id) => {
    if (typeof id === 'string') {
      if (id !== activeId.value) selectConversation(id, { navigate: false })
    } else {
      router.replace(`/c/${activeId.value}`)
    }
  },
  { immediate: true },
)
</script>

<template>
  <ChatWindow
    :messages="messages"
    @send="sendMessage"
    @regenerate="regenerateMessage"
    @feedback="sendFeedback"
    @show-sources="showSources"
    @show-execution="showExecutionDetails"
    @show-discussion-score="showDiscussionPanel = true"
  />
  <SourcesPanel v-if="activeSources?.length" :sources="activeSources" @close="closeSources" />
  <ExecutionPanel
    v-else-if="activeExecutionMessageId"
    :events="activeExecutionEvents"
    :error="activeExecutionError"
    @close="closeExecutionDetails"
  />
  <DiscussionScorePanel
    v-else-if="showDiscussionPanel"
    @close="showDiscussionPanel = false"
  />
</template>
