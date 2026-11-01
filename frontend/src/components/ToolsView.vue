<script setup lang="ts">
// Les outils que le chat peut appeler (#343) : ceux de Muffin, et ceux des serveurs MCP que les utilisateurs ajoutent.
import { computed, onMounted, ref } from 'vue'
import { useToolSearch } from '../composables/useToolSearch'
import { useTools } from '../composables/useTools'
import type { ToolServer } from '../types/tool'
import ToolServerForm from './ToolServerForm.vue'

const { servers, tools, isLoading, toolError, refreshServers, refreshTools, setEnabled, syncServer, deleteServer } = useTools()
// Chercher un outil par ce qu'il fait (#530) : une phrase, pas seulement un mot de son nom. Triés par pertinence.
const { query, results, active, loading } = useToolSearch(tools)

const editing = ref<{ id: string | null } | null>(null)
const syncing = ref<string | null>(null)

onMounted(() => {
  refreshServers()
  refreshTools()
})

const own = computed(() => servers.value.filter((item) => item.isOwner))
const shared = computed(() => servers.value.filter((item) => !item.isOwner))
const internal = computed(() => tools.value.filter((tool) => tool.serverId === null))
const current = computed(() => (editing.value?.id ? (servers.value.find((item) => item.id === editing.value!.id) ?? null) : null))
async function sync(server: ToolServer) {
  syncing.value = server.id
  await syncServer(server.id)
  await refreshTools()
  syncing.value = null
}

async function remove(server: ToolServer) {
  if (!confirm(`Supprimer le serveur « ${server.name} » et ses outils ? Son jeton est effacé.`)) return
  await deleteServer(server.id)
  await refreshTools()
}

async function toggle(server: ToolServer) {
  await setEnabled(server.id, !server.enabled)
  await refreshTools()
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString('fr-FR') : 'jamais'
}

async function saved() {
  editing.value = null
  await refreshTools()
}
</script>

<template>
  <section class="tools-view">
    <header class="tools-view__head">
      <h1>Outils</h1>
      <button type="button" class="fr-btn" @click="editing = { id: null }">Ajouter un serveur</button>
    </header>
    <p class="tools-view__intro">
      Le chat peut appeler des <strong>outils</strong> : ceux de Muffin (calcul, dates, et la génération d’images quand
      l’administrateur l’a activée) et ceux des <strong>serveurs MCP</strong> que
      vous ajoutez. Il les appelle <strong>en votre nom</strong>, avec un quota, et chaque appel est journalisé sans ses arguments ni sa
      réponse. Un outil qui <strong>modifie des données</strong> n’est jamais appelé sans votre accord : l’assistant le <strong>propose</strong>
      dans la discussion, avec ses arguments, et ne le lance que si vous l’autorisez.
    </p>
    <p v-if="toolError && !editing" class="tools-view__error" role="alert">{{ toolError }}</p>

    <div v-if="editing" class="tools-view__panel">
      <h2>{{ current ? `Modifier « ${current.name} »` : 'Ajouter un serveur MCP' }}</h2>
      <ToolServerForm :key="editing.id ?? 'new'" :server="current" @saved="saved" @cancel="editing = null" />
    </div>

    <template v-else>
      <div v-if="tools.length > 6" class="tools-view__search" role="search">
        <label class="fr-label" for="tools-filter">
          Chercher un outil
          <span class="fr-hint-text">Décrivez ce que vous voulez faire : « convertir une devise », « retrouver un dossier »…</span>
        </label>
        <input id="tools-filter" v-model="query" type="search" class="fr-input" placeholder="Ce qu’il fait…" autocomplete="off" />
      </div>

      <template v-if="active">
        <h2>Résultats</h2>
        <p v-if="loading" class="tools-view__empty" role="status">Recherche…</p>
        <p v-else-if="!results.length" class="tools-view__empty" role="status">Aucun outil ne correspond à « {{ query.trim() }} ».</p>
        <ul v-else class="tools-view__tools" aria-label="Outils trouvés, du plus proche au moins proche">
          <li v-for="tool in results" :key="tool.ref" class="tools-view__tool">
            <strong>{{ tool.name }}<span v-if="tool.serverName" class="tools-view__meta"> · {{ tool.serverName }}</span></strong>
            <span v-if="tool.sideEffect" class="tools-view__badge">modifie des données · votre accord est demandé</span>
            <span class="tools-view__description">{{ tool.description }}</span>
          </li>
        </ul>
      </template>

      <template v-else>
        <h2>Outils de Muffin</h2>
        <ul class="tools-view__tools">
          <li v-for="tool in internal" :key="tool.ref" class="tools-view__tool">
            <strong>{{ tool.name }}</strong>
            <span class="tools-view__description">{{ tool.description }}</span>
          </li>
        </ul>

        <p v-if="isLoading && !servers.length" class="tools-view__empty">Chargement…</p>
        <p v-else-if="!servers.length" class="tools-view__empty">
          Aucun serveur MCP pour l’instant. Ajoutez-en un pour donner d’autres outils au chat.
        </p>

        <template v-for="group in [{ title: 'Mes serveurs', items: own }, { title: 'Partagés avec moi', items: shared }]" :key="group.title">
          <template v-if="group.items.length">
            <h2>{{ group.title }}</h2>
            <ul class="tools-view__servers">
              <li v-for="server in group.items" :key="server.id" class="tools-view__server">
                <div class="tools-view__server-head">
                  <div class="tools-view__text">
                    <strong>{{ server.name }}</strong>
                    <span class="tools-view__description">{{ server.url }}</span>
                    <span class="tools-view__meta">
                      {{ server.enabled ? '' : 'Désactivé · ' }}{{ { private: 'Privé', groups: 'Partagé avec des groupes', all: 'Toute l’organisation' }[server.visibility] }}
                      · {{ server.authMode === 'bearer' ? 'avec jeton' : 'sans jeton' }} · synchronisé : {{ when(server.lastSyncedAt) }}
                    </span>
                    <span v-if="server.lastError" class="tools-view__warning" role="status">{{ server.lastError }}</span>
                  </div>
                  <div v-if="server.isOwner" class="tools-view__actions">
                    <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" :disabled="syncing === server.id" @click="sync(server)">
                      {{ syncing === server.id ? 'Connexion…' : 'Tester et synchroniser' }}
                    </button>
                    <button type="button" class="fr-btn fr-btn--sm fr-btn--secondary" @click="editing = { id: server.id }">Modifier</button>
                    <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="toggle(server)">
                      {{ server.enabled ? 'Désactiver' : 'Activer' }}
                    </button>
                    <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="remove(server)">Supprimer</button>
                  </div>
                </div>
                <ul v-if="server.tools.length" class="tools-view__tools">
                  <li v-for="tool in server.tools" :key="tool.ref" class="tools-view__tool">
                    <strong>{{ tool.name }}</strong>
                    <span v-if="tool.sideEffect" class="tools-view__badge" :title="tool.reason ?? ''">modifie des données · votre accord est demandé</span>
                    <span class="tools-view__description">{{ tool.description }}</span>
                  </li>
                </ul>
                <p v-else class="tools-view__empty">Aucun outil importé.</p>
              </li>
            </ul>
          </template>
        </template>
      </template>
    </template>
  </section>
</template>

<style scoped>
.tools-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.tools-view > * {
  max-width: 52rem;
  margin-left: auto;
  margin-right: auto;
}

.tools-view h2 {
  margin-top: 2rem;
}

.tools-view__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.tools-view__panel {
  margin-top: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.tools-view__servers,
.tools-view__tools {
  list-style: none;
  margin: 0.75rem auto 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.tools-view__server {
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
}

.tools-view__server-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.75rem;
}

.tools-view__text {
  flex: 1;
  min-width: 12rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  overflow-wrap: anywhere;
}

.tools-view__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.tools-view__tool {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
  padding: 0.375rem 0;
}

.tools-view__description,
.tools-view__meta {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.tools-view__badge {
  align-self: flex-start;
  padding: 0.0625rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  background: var(--background-contrast-warning);
  color: var(--text-default-warning);
}

.tools-view__warning {
  font-size: 0.8125rem;
  color: var(--text-default-warning);
}

.tools-view__search {
  margin-top: 1rem;
}

.tools-view__empty {
  margin-top: 1rem;
  color: var(--text-mention-grey);
}

.tools-view__error {
  color: var(--text-default-error);
}
</style>
