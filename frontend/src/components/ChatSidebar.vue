<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Conversation } from '../types/chat'
import type { User } from '../types/user'
import ConversationMenu from './ConversationMenu.vue'

defineProps<{
  conversations: Conversation[]
  activeId: string
  activeView: 'chat' | 'collections' | 'tasks' | 'admin'
  user: User | null
}>()

const emit = defineEmits<{
  select: [id: string]
  new: []
  rename: [id: string, title: string]
  delete: [id: string]
  openCollections: []
  openTasks: []
  openAdmin: []
  openSettings: []
  login: []
  logout: []
}>()

const showUserMenu = ref(false)
const userWrapper = ref<HTMLElement>()

const renamingId = ref<string>()
const renameDraft = ref('')
const renameInput = ref<HTMLInputElement | null>(null)

async function startRename(conversation: Conversation) {
  renamingId.value = conversation.id
  renameDraft.value = conversation.title
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}

function confirmRename() {
  const id = renamingId.value
  const title = renameDraft.value.trim()
  renamingId.value = undefined
  if (id && title) emit('rename', id, title)
}

function cancelRename() {
  renamingId.value = undefined
}

function deleteConversation(conversation: Conversation) {
  if (window.confirm(`Supprimer « ${conversation.title} » ? Cette action est irréversible.`)) {
    emit('delete', conversation.id)
  }
}

function openSettings() {
  showUserMenu.value = false
  emit('openSettings')
}

function openTasks() {
  showUserMenu.value = false
  emit('openTasks')
}

function openAdmin() {
  showUserMenu.value = false
  emit('openAdmin')
}

function logout() {
  showUserMenu.value = false
  emit('logout')
}

function handleOutsideClick(event: MouseEvent) {
  if (showUserMenu.value && !userWrapper.value?.contains(event.target as Node)) {
    showUserMenu.value = false
  }
}

onMounted(() => document.addEventListener('click', handleOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', handleOutsideClick))

function initials(name: string) {
  return name
    .split(' ')
    .map((part) => part.charAt(0))
    .slice(0, 2)
    .join('')
    .toUpperCase()
}
</script>

<template>
  <aside class="chat-sidebar">
    <div class="chat-sidebar__brand">
      <p class="fr-logo chat-sidebar__logo">Muffin</p>
    </div>

    <button type="button" class="chat-sidebar__new" @click="emit('new')">
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path
          fill="currentColor"
          d="M17.7 3.3a1 1 0 0 1 1.4 0l1.6 1.6a1 1 0 0 1 0 1.4L9.5 17.5l-4.2 1 1-4.2L17.7 3.3z"
        />
      </svg>
      Nouveau chat
    </button>

    <nav class="chat-sidebar__nav" aria-label="Navigation principale">
      <button
        type="button"
        class="chat-sidebar__nav-item"
        :class="{ 'chat-sidebar__nav-item--active': activeView === 'collections' }"
        @click="emit('openCollections')"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            fill="currentColor"
            d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z"
          />
        </svg>
        Collections
      </button>
    </nav>

    <div class="chat-sidebar__scroll">
      <h2 class="chat-sidebar__section-title">Récents</h2>
      <nav class="chat-sidebar__list" aria-label="Historique des conversations">
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="chat-sidebar__row"
          :class="{ 'chat-sidebar__row--active': activeView === 'chat' && conversation.id === activeId }"
        >
          <input
            v-if="renamingId === conversation.id"
            :ref="(el) => (renameInput = el as HTMLInputElement | null)"
            v-model="renameDraft"
            type="text"
            class="chat-sidebar__rename-input"
            aria-label="Renommer la conversation"
            @keydown.enter="confirmRename"
            @keydown.escape="cancelRename"
            @blur="confirmRename"
            @click.stop
          />
          <button
            v-else
            type="button"
            class="chat-sidebar__item"
            @click="emit('select', conversation.id)"
          >
            {{ conversation.title }}
          </button>

          <ConversationMenu
            v-if="renamingId !== conversation.id"
            class="chat-sidebar__row-menu"
            @rename="startRename(conversation)"
            @delete="deleteConversation(conversation)"
          />
        </div>
      </nav>
    </div>

    <div v-if="user" ref="userWrapper" class="chat-sidebar__user-wrapper">
      <div v-if="showUserMenu" class="user-menu" role="menu">
        <button type="button" class="user-menu__item" role="menuitem" @click="openSettings">
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path
              fill="currentColor"
              d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm7.4 3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1c.6.5 1.3.9 2 1.2l.4 2.6h4l.4-2.6c.7-.3 1.4-.7 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z"
            />
          </svg>
          Paramètres
        </button>
        <button type="button" class="user-menu__item" role="menuitem" @click="openTasks">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 11l3 3 8-8M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9" />
          </svg>
          Tâches
        </button>
        <button v-if="user?.isAdmin" type="button" class="user-menu__item" role="menuitem" @click="openAdmin">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M12 3l7 3.5v5.5c0 4-3 6.5-7 8-4-1.5-7-4-7-8V6.5L12 3z"
            />
          </svg>
          Administration
        </button>
        <button type="button" class="user-menu__item" role="menuitem" @click="logout">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M8.25 9V5.25A2.25 2.25 0 0 1 10.5 3h6a2.25 2.25 0 0 1 2.25 2.25v13.5A2.25 2.25 0 0 1 16.5 21h-6a2.25 2.25 0 0 1-2.25-2.25V15M3 12h13.5m0 0-3-3m3 3-3 3"
            />
          </svg>
          Se déconnecter
        </button>
      </div>

      <button type="button" class="chat-sidebar__user" @click="showUserMenu = !showUserMenu">
        <span class="chat-sidebar__avatar" aria-hidden="true">{{ initials(user.name) }}</span>
        <div class="chat-sidebar__user-info">
          <span class="chat-sidebar__user-name">{{ user.name }}</span>
          <span class="chat-sidebar__user-email">{{ user.email }}</span>
        </div>
      </button>
    </div>

    <button v-else type="button" class="chat-sidebar__user chat-sidebar__login" @click="emit('login')">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M21 12H8.25m0 0 3 3m-3-3 3-3"
        />
      </svg>
      Se connecter
    </button>
  </aside>
</template>

<style scoped>
.chat-sidebar {
  display: flex;
  flex-direction: column;
  width: 260px;
  flex-shrink: 0;
  height: 100%;
  padding: 0.75rem;
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
  border-right: 1px solid var(--border-default-grey);
  box-sizing: border-box;
}

.chat-sidebar__brand {
  padding: 0.5rem 0.75rem 1rem;
}

.chat-sidebar__logo {
  font-size: 1.05rem;
}

.chat-sidebar__new,
.chat-sidebar__nav-item,
.chat-sidebar__user {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  text-align: left;
  padding: 0.625rem 0.75rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
}

.chat-sidebar__new:hover,
.chat-sidebar__nav-item:hover,
.chat-sidebar__user:hover {
  background: var(--background-alt-grey-hover);
}

.chat-sidebar__nav-item--active {
  background: var(--background-alt-blue-france);
  font-weight: 600;
}

.chat-sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  margin-top: 0.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.chat-sidebar__scroll {
  flex: 1;
  overflow-y: auto;
  margin-top: 0.75rem;
}

.chat-sidebar__section-title {
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--text-mention-grey);
  margin: 0 0 0.25rem 0.75rem;
}

.chat-sidebar__list {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.chat-sidebar__row {
  display: flex;
  align-items: center;
  border-radius: 0.5rem;
}

.chat-sidebar__row:hover,
.chat-sidebar__row:focus-within {
  background: var(--background-alt-grey-hover);
}

.chat-sidebar__row--active {
  background: var(--background-alt-blue-france);
}

.chat-sidebar__row--active .chat-sidebar__item {
  font-weight: 600;
}

.chat-sidebar__item {
  flex: 1;
  min-width: 0;
  padding: 0.625rem 0.75rem;
  border: none;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-sidebar__row-menu {
  flex-shrink: 0;
  margin-right: 0.25rem;
  opacity: 0;
}

.chat-sidebar__row:hover .chat-sidebar__row-menu,
.chat-sidebar__row:focus-within .chat-sidebar__row-menu {
  opacity: 1;
}

.chat-sidebar__rename-input {
  flex: 1;
  min-width: 0;
  margin: 0.3125rem 0.75rem;
  padding: 0.3125rem 0.5rem;
  border-radius: 0.375rem;
  border: 1px solid var(--border-action-high-blue-france);
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
  box-sizing: border-box;
}

.chat-sidebar__rename-input:focus {
  outline: none;
}

.chat-sidebar__user-wrapper {
  position: relative;
  flex-shrink: 0;
}

.chat-sidebar__user {
  margin-top: 0.5rem;
  border-top: 1px solid var(--border-default-grey);
  border-radius: 0;
  padding-top: 0.75rem;
}

.user-menu {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 0.5rem;
  padding: 0.25rem;
  background: var(--background-default-grey);
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.user-menu__item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  text-align: left;
  padding: 0.625rem 0.75rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.875rem;
  font-family: inherit;
}

.user-menu__item:hover {
  background: var(--background-alt-grey-hover);
}

.chat-sidebar__avatar {
  flex-shrink: 0;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--text-inverted-blue-france);
  background: var(--background-action-high-blue-france);
}

.chat-sidebar__user-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-sidebar__user-name {
  font-size: 0.875rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-sidebar__user-email {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
