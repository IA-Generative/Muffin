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
const { conversations, activeId, selectConversation, newConversation } = useChat()

const activeView = computed(() => {
  if (route.path.startsWith('/collections')) return 'collections'
  if (route.path.startsWith('/tasks')) return 'tasks'
  return 'chat'
})
</script>

<template>
  <div class="chat-layout">
    <ChatSidebar
      :conversations="conversations"
      :active-id="activeId"
      :active-view="activeView"
      :user="user"
      @select="selectConversation"
      @new="newConversation"
      @open-collections="router.push('/collections')"
      @open-tasks="router.push('/tasks')"
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
