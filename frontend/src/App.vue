<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChatSidebar from './components/ChatSidebar.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useChat } from './composables/useChat'
import { useCurrentUser } from './composables/useCurrentUser'

const route = useRoute()
const router = useRouter()
const showSettings = ref(false)

const { user, login, logout } = useCurrentUser()
const {
  conversations,
  conversationsHasMore,
  loadingMoreConversations,
  loadMoreConversations,
  activeId,
  selectConversation,
  newConversation,
  renameConversation,
  deleteConversation,
} = useChat()

const activeView = computed(() => {
  if (route.path.startsWith('/collections')) return 'collections'
  if (route.path.startsWith('/tasks')) return 'tasks'
  if (route.path.startsWith('/admin')) return 'admin'
  return 'chat'
})
</script>

<template>
  <div class="chat-layout">
    <ChatSidebar
      :conversations="conversations"
      :conversations-has-more="conversationsHasMore"
      :loading-more-conversations="loadingMoreConversations"
      :active-id="activeId"
      :active-view="activeView"
      :user="user"
      @select="selectConversation"
      @load-more="loadMoreConversations"
      @new="newConversation"
      @rename="renameConversation"
      @delete="deleteConversation"
      @open-collections="router.push('/collections')"
      @open-tasks="router.push('/tasks')"
      @open-admin="router.push('/admin')"
      @open-settings="showSettings = true"
      @login="login()"
      @logout="logout"
    />
    <router-view />

    <SettingsModal v-if="showSettings" @close="showSettings = false" />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}
</style>
