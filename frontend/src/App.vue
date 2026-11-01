<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CguGateModal from './components/CguGateModal.vue'
import ChatSidebar from './components/ChatSidebar.vue'
import HomeView from './components/HomeView.vue'
import OnboardingModal from './components/OnboardingModal.vue'
import ApiKeysModal from './components/ApiKeysModal.vue'
import SettingsModal from './components/SettingsModal.vue'
import { useCgu } from './composables/useCgu'
import { useChat } from './composables/useChat'
import { useCurrentUser } from './composables/useCurrentUser'
import { useOnboarding } from './composables/useOnboarding'

const route = useRoute()
const router = useRouter()
const showSettings = ref(false)
const showApiKeys = ref(false)

const { user, isAuthenticated, isLoading, login, logout } = useCurrentUser()
const { status: cguStatus, fetchCguStatus } = useCgu()
// /cgu/status requires a session - only fetched once one exists, but as soon as it does (§127:
// gates the whole app, not just a specific page, so this can't wait for a component that needs
// it to mount first).
watch(isAuthenticated, (authenticated) => authenticated && fetchCguStatus(), { immediate: true })

const { showTutorial, dismissedForever, openTutorial } = useOnboarding()
// Auto-opens once per page load, and only once the CGU gate (if any) is already cleared - never
// stack two blocking modals, and never re-open on every unrelated reactivity tick once the user
// has closed it for this session (§135).
let onboardingAutoOpened = false
watch(
  () => [isAuthenticated.value, cguStatus.value, dismissedForever.value] as const,
  ([authenticated, status, dismissed]) => {
    if (onboardingAutoOpened || dismissed || !authenticated || !status?.accepted) return
    onboardingAutoOpened = true
    openTutorial()
  },
  { immediate: true },
)
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
  if (route.path.startsWith('/assistants')) return 'assistants'
  if (route.path.startsWith('/tools')) return 'tools'
  if (route.path.startsWith('/groups')) return 'groups'
  if (route.path.startsWith('/tasks')) return 'tasks'
  if (route.path.startsWith('/quality')) return 'quality'
  if (route.path.startsWith('/usage')) return 'usage'
  if (route.path.startsWith('/admin')) return 'admin'
  if (route.path.startsWith('/filing')) return 'filing'
  return 'chat'
})
</script>

<template>
  <HomeView v-if="!isLoading && !isAuthenticated" @login="login()" />

  <div v-else-if="!isLoading" class="chat-layout">
    <ChatSidebar
      :conversations="conversations"
      :conversations-has-more="conversationsHasMore"
      :loading-more-conversations="loadingMoreConversations"
      :active-id="activeId"
      :active-view="activeView"
      :user="user"
      @select="selectConversation"
      @select-message="(id: string, messageId: string) => selectConversation(id, { messageId })"
      @load-more="loadMoreConversations"
      @new="newConversation"
      @rename="renameConversation"
      @delete="deleteConversation"
      @open-collections="router.push('/collections')"
      @open-assistants="router.push('/assistants')"
      @open-tools="router.push('/tools')"
      @open-groups="router.push('/groups')"
      @open-tasks="router.push('/tasks')"
      @open-quality="router.push('/quality')"
      @open-usage="router.push('/usage')"
      @open-admin="router.push('/admin')"
      @open-filing="router.push('/filing')"
      @open-settings="showSettings = true"
      @open-api-keys="showApiKeys = true"
      @login="login()"
      @logout="logout"
    />
    <router-view />

    <SettingsModal v-if="showSettings" @close="showSettings = false" />
    <ApiKeysModal v-if="showApiKeys" @close="showApiKeys = false" />
    <CguGateModal v-if="isAuthenticated && cguStatus && !cguStatus.accepted" />
    <OnboardingModal v-if="showTutorial" />
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
}
</style>
