<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  toggle: []
  close: []
  rename: []
  delete: []
}>()

const trigger = ref<HTMLElement>()
const position = ref({ bottom: 0, right: 0 })

// Teleported to <body> (below), so this can't be clipped by the sidebar's own scrolling list -
// position is computed from the trigger's real screen position instead of relying on CSS
// containment, which is what let the first row's dropdown get cut off before.
async function updatePosition() {
  await nextTick()
  const rect = trigger.value?.getBoundingClientRect()
  if (!rect) return
  position.value = { bottom: window.innerHeight - rect.top + 4, right: window.innerWidth - rect.right }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) updatePosition()
  },
)

function onTriggerClick(event: MouseEvent) {
  event.stopPropagation() // never trigger the conversation row's own @click underneath
  emit('toggle')
}

function rename() {
  emit('close')
  emit('rename')
}

function remove() {
  emit('close')
  emit('delete')
}
</script>

<template>
  <button
    ref="trigger"
    v-bind="$attrs"
    type="button"
    class="conversation-menu__trigger"
    :class="{ 'conversation-menu__trigger--open': open }"
    :style="{ opacity: open ? 1 : undefined }"
    aria-label="Options de la conversation"
    @click="onTriggerClick"
  >
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <circle cx="5" cy="12" r="1.75" fill="currentColor" />
      <circle cx="12" cy="12" r="1.75" fill="currentColor" />
      <circle cx="19" cy="12" r="1.75" fill="currentColor" />
    </svg>
  </button>

  <Teleport to="body">
    <div
      v-if="open"
      class="conversation-menu__dropdown"
      role="menu"
      :style="{ bottom: `${position.bottom}px`, right: `${position.right}px` }"
      @click.stop
    >
      <button type="button" class="conversation-menu__item" role="menuitem" @click="rename">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Z"
          />
        </svg>
        Renommer
      </button>
      <button type="button" class="conversation-menu__item" role="menuitem" disabled title="Bientôt disponible">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M7.217 10.907a2.25 2.25 0 1 0 0 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186 9.566-5.314m-9.566 7.5 9.566 5.314m0 0a2.25 2.25 0 1 0 3.935 2.186 2.25 2.25 0 0 0-3.935-2.186Zm0-12.814a2.25 2.25 0 1 0 3.933-2.185 2.25 2.25 0 0 0-3.933 2.185Z"
          />
        </svg>
        Partager
      </button>
      <button type="button" class="conversation-menu__item" role="menuitem" disabled title="Bientôt disponible">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M9.568 3.166a1 1 0 0 1 1.264-.634l.005.002.011.004.033.012a5.201 5.201 0 0 1 .391.163 8.72 8.72 0 0 1 1.7 1.033C14.06 4.61 15 6.229 15 8.5c0 1.859.577 3.15 1.147 3.964.286.408.568.694.777.876.104.09.19.152.242.19l.041.028a1 1 0 0 1-.526 1.842H6.319a1 1 0 0 1-.526-1.842l.04-.028a3.03 3.03 0 0 0 .243-.19 4.146 4.146 0 0 0 .777-.876C7.423 11.649 8 10.359 8 8.5c0-2.271.94-3.89 2.028-4.755a8.72 8.72 0 0 1 1.541-.977Z"
          />
          <path stroke-linecap="round" stroke-linejoin="round" d="M11 18a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2Z" />
        </svg>
        Épingler
      </button>
      <button type="button" class="conversation-menu__item conversation-menu__item--danger" role="menuitem" @click="remove">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
          />
        </svg>
        Supprimer
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.conversation-menu__trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 1.75rem;
  height: 1.75rem;
  padding: 0;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
}

.conversation-menu__trigger:hover,
.conversation-menu__trigger--open {
  background: var(--background-alt-grey-hover);
  color: var(--text-default-grey);
}
</style>

<style>
/* Unscoped: teleported to <body>, outside this component's own DOM subtree, so Vue's scoped
   attribute selectors would never match it. */
.conversation-menu__dropdown {
  position: fixed;
  z-index: 1000;
  min-width: 10rem;
  padding: 0.25rem;
  background: var(--background-default-grey);
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.conversation-menu__item {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  text-align: left;
  padding: 0.5rem 0.625rem;
  border: none;
  border-radius: 0.375rem;
  background: transparent;
  color: var(--text-default-grey);
  cursor: pointer;
  font-size: 0.8125rem;
  font-family: inherit;
  white-space: nowrap;
}

.conversation-menu__item:hover:not(:disabled) {
  background: var(--background-alt-grey-hover);
}

.conversation-menu__item:disabled {
  color: var(--text-disabled-grey);
  cursor: not-allowed;
}

.conversation-menu__item--danger {
  color: var(--text-default-error);
}

.conversation-menu__item--danger:hover {
  background: var(--background-alt-error);
}
</style>
