<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts, dismissToast } = useToast()
</script>

<template>
  <!--
    Global toast rack: transient notifications pushed from anywhere via useToast's pushToast.
    Fixed bottom-right, above modals (z-index 1100 > the app's modal layers), each toast styled
    as a DSFR alert and auto-dismissed by the composable's timer. aria-live announces pushes
    without stealing focus the way a modal would.
  -->
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="toast in toasts" :key="toast.id" class="fr-alert" :class="`fr-alert--${toast.type}`">
        <h3 class="fr-alert__title">{{ toast.title }}</h3>
        <p v-if="toast.description">{{ toast.description }}</p>
        <button type="button" class="fr-btn fr-btn--close" title="Masquer le message" @click="dismissToast(toast.id)">
          Masquer le message
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  z-index: 1100;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  /* Shrink-to-fit: an empty rack occupies no space and blocks nothing. */
  max-width: min(26rem, calc(100vw - 2rem));
}

.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.3s ease,
    transform 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(1rem);
}
</style>
