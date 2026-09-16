<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChat } from '../composables/useChat'
import ChatWindow from './ChatWindow.vue'
import SourcesPanel from './SourcesPanel.vue'

const route = useRoute()
const router = useRouter()

const { activeId, messages, activeSources, selectConversation, sendMessage, regenerateMessage, sendFeedback, showSources, closeSources } =
  useChat()

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
  />
  <SourcesPanel v-if="activeSources?.length" :sources="activeSources" @close="closeSources" />
</template>
