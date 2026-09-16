<script setup lang="ts">
import { useChat } from '../composables/useChat'
import ChatWindow from './ChatWindow.vue'
import SourcesPanel from './SourcesPanel.vue'

const { messages, activeSources, sendMessage, regenerateMessage, sendFeedback, showSources, closeSources } =
  useChat()
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
