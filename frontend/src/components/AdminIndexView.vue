<script setup lang="ts">
interface AdminItem {
  key: string
  label: string
  description: string
  path: string
}

const items: AdminItem[] = [
  {
    key: 'settings',
    label: 'Paramètres',
    description: "Modèle d'embedding global, utilisé pour router les questions entre collections.",
    path: '/admin/settings',
  },
  {
    key: 'prompts',
    label: "Prompts de l'agent",
    description: 'Historique et publication des prompts système utilisés par le graphe de recherche.',
    path: '/admin/prompts',
  },
  {
    key: 'cgu',
    label: 'Conditions générales d\'utilisation',
    description: 'Versions des CGU, acceptation obligatoire des utilisateurs.',
    path: '/admin/cgu',
  },
  {
    key: 'reports',
    label: 'Signalements',
    description: 'Bugs, idées et questions envoyés par les utilisateurs.',
    path: '/admin/reports',
  },
]
</script>

<template>
  <section class="admin-index">
    <div class="admin-index__header">
      <h1>Administration</h1>
    </div>
    <p class="admin-index__intro">Réglages globaux, valables pour toutes les collections.</p>

    <div class="admin-index__grid">
      <router-link v-for="item in items" :key="item.key" :to="item.path" class="admin-index__card">
        <span class="admin-index__card-title">{{ item.label }}</span>
        <span class="admin-index__card-description">{{ item.description }}</span>
      </router-link>
    </div>
  </section>
</template>

<style scoped>
.admin-index {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.admin-index__header {
  max-width: 48rem;
  margin: 0 auto;
}

.admin-index__header h1 {
  margin: 0;
}

.admin-index__intro {
  max-width: 48rem;
  margin: 0.5rem auto 1.5rem;
  color: var(--text-mention-grey);
}

.admin-index__grid {
  max-width: 48rem;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.admin-index__card {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  color: inherit;
  text-decoration: none;
  box-sizing: border-box;
}

.admin-index__card:hover {
  border-color: var(--border-action-high-blue-france);
}

.admin-index__card-title {
  font-weight: 700;
  font-size: 1rem;
}

.admin-index__card-description {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}
</style>
