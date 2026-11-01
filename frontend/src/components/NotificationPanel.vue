<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { type AppNotification, useNotifications } from '../composables/useNotifications'
import { formatDateTime } from '../utils/routines'

defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ close: [] }>()

const router = useRouter()
const { items, unread, hasMore, isLoading, error, loadFirstPage, loadMore, markRead, remove } = useNotifications()

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  void loadFirstPage()
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

async function open(notification: AppNotification) {
  if (!notification.read) void markRead([notification.id])
  if (notification.link) {
    emit('close')
    await router.push(notification.link)
  }
}
</script>

<template>
  <div class="notification-panel__backdrop" @click.self="emit('close')">
    <section
      class="notification-panel"
      :class="{ 'notification-panel--collapsed': collapsed }"
      role="dialog"
      aria-labelledby="notification-panel-title"
    >
      <header class="notification-panel__header">
        <h2 id="notification-panel-title">Notifications</h2>
        <button v-if="unread" type="button" class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm" @click="markRead()">
          Tout marquer comme lu
        </button>
        <button type="button" class="notification-panel__close" aria-label="Fermer les notifications" @click="emit('close')">
          ✕
        </button>
      </header>

      <p v-if="error" class="notification-panel__message notification-panel__message--error" role="alert">{{ error }}</p>
      <p v-else-if="!items.length && !isLoading" class="notification-panel__message">
        Rien pour le moment. Vous serez prévenu ici d’un résultat de routine, d’un document qui n’a pas pu être traité, d’un
        import terminé ou d’un partage.
      </p>

      <ul v-if="items.length" class="notification-panel__list">
        <li v-for="item in items" :key="item.id" class="notification-panel__item" :class="{ 'notification-panel__item--unread': !item.read }">
          <button type="button" class="notification-panel__open" @click="open(item)">
            <span v-if="!item.read" class="fr-sr-only">Non lue : </span>
            <span class="notification-panel__title">{{ item.title }}</span>
            <span v-if="item.summary" class="notification-panel__summary">{{ item.summary }}</span>
            <time class="notification-panel__date" :datetime="item.createdAt">{{ formatDateTime(item.createdAt) }}</time>
          </button>
          <button type="button" class="notification-panel__remove" :aria-label="`Supprimer la notification « ${item.title} »`" @click="remove(item.id)">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </li>
      </ul>

      <footer v-if="hasMore" class="notification-panel__footer">
        <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" :disabled="isLoading" @click="loadMore">
          Voir les plus anciennes
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.notification-panel__backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
}

.notification-panel {
  position: absolute;
  top: 4rem;
  left: 16.5rem;
  display: flex;
  flex-direction: column;
  width: min(26rem, calc(100vw - 18rem));
  max-height: 70vh;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.notification-panel--collapsed {
  left: 5rem;
}

.notification-panel__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.notification-panel__header h2 {
  margin: 0 auto 0 0;
  font-size: 1rem;
}

.notification-panel__close,
.notification-panel__remove {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-mention-grey);
  padding: 0.25rem 0.375rem;
}

.notification-panel__message {
  margin: 0;
  padding: 1.25rem 1rem;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.notification-panel__message--error {
  color: var(--text-default-error);
}

.notification-panel__list {
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-y: auto;
}

.notification-panel__item {
  display: flex;
  align-items: flex-start;
  border-bottom: 1px solid var(--border-default-grey);
}

.notification-panel__item--unread {
  background: var(--background-alt-blue-france);
}

.notification-panel__open {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.125rem;
  padding: 0.625rem 1rem;
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
}

.notification-panel__open:hover {
  background: var(--background-alt-grey-hover);
}

.notification-panel__title {
  font-size: 0.875rem;
  font-weight: 600;
}

.notification-panel__summary {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.notification-panel__date {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.notification-panel__remove {
  margin: 0.5rem 0.5rem 0 0;
}

.notification-panel__footer {
  display: flex;
  justify-content: center;
  padding: 0.5rem;
  border-top: 1px solid var(--border-default-grey);
}
</style>
