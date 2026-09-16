<script setup lang="ts">
import { ref } from 'vue'
import ChatSidebar from './components/ChatSidebar.vue'
import ChatView from './components/ChatView.vue'
import CollectionsView from './components/CollectionsView.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useChat } from './composables/useChat'
import { useCurrentUser } from './composables/useCurrentUser'

const view = ref<'chat' | 'collections'>('chat')
const showSettings = ref(false)

const { user } = useCurrentUser()
const { conversations, activeId, selectConversation, newConversation } = useChat()

function selectConversationAndShowChat(id: string) {
  view.value = 'chat'
  selectConversation(id)
}

function newConversationAndShowChat() {
  newConversation()
  view.value = 'chat'
}
</script>

<template>
  <div class="chat-layout">
    <ChatSidebar
      :conversations="conversations"
      :active-id="activeId"
      :active-view="view"
      :user="user"
      @select="selectConversationAndShowChat"
      @new="newConversationAndShowChat"
      @open-collections="view = 'collections'"
      @open-settings="showSettings = true"
    />
    <ChatView v-if="view === 'chat'" />
    <CollectionsView v-else />

    <SettingsModal v-if="showSettings" @close="showSettings = false" />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}
</style>
