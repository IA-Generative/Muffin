<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CguGateModal from './components/CguGateModal.vue'
import ChatSidebar from './components/ChatSidebar.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useCgu } from './composables/useCgu'
import { useChat } from './composables/useChat'
import { useCurrentUser } from './composables/useCurrentUser'

const route = useRoute()
const router = useRouter()
const showSettings = ref(false)

const { user, isAuthenticated, login, logout } = useCurrentUser()
const { status: cguStatus, fetchCguStatus } = useCgu()
// /cgu/status requires a session - only fetched once one exists, but as soon as it does (§127:
// gates the whole app, not just a specific page, so this can't wait for a component that needs
// it to mount first).
watch(isAuthenticated, (authenticated) => authenticated && fetchCguStatus(), { immediate: true })
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
  if (route.path.startsWith('/quality')) return 'quality'
  if (route.path.startsWith('/admin')) return 'admin'
  if (route.path.startsWith('/filing')) return 'filing'
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
      @open-quality="router.push('/quality')"
      @open-admin="router.push('/admin')"
      @open-filing="router.push('/filing')"
      @open-settings="showSettings = true"
      @login="login()"
      @logout="logout"
    />
    <router-view />

    <SettingsModal v-if="showSettings" @close="showSettings = false" />
    <CguGateModal v-if="isAuthenticated && cguStatus && !cguStatus.accepted" />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}
</style>
