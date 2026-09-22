<script setup lang="ts">
import ReportsAdminSection from './ReportsAdminSection.vue'
</script>

<template>
  <section class="admin-view">
    <router-link to="/admin" class="admin-view__back">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
      </svg>
      Administration
    </router-link>
    <div class="admin-view__header">
      <h1>Signalements</h1>
    </div>
    <p class="admin-view__intro">
      Bugs, idées et questions envoyés par les utilisateurs depuis le menu utilisateur - voir #148.
    </p>
    <ReportsAdminSection class="admin-card-frame" />
  </section>
</template>

<style scoped>
.admin-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.admin-view__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  max-width: 48rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__back:hover {
  color: var(--text-default-grey);
}

.admin-view__header {
  max-width: 48rem;
  margin: 0 auto;
}

.admin-view__header h1 {
  margin: 0;
}

.admin-view__intro {
  max-width: 48rem;
  margin: 0.5rem auto 1.5rem;
  color: var(--text-mention-grey);
}

.admin-card-frame {
  max-width: 48rem;
  margin: 0 auto;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}
</style>
