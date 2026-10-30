<script setup lang="ts">
// Mes groupes : ceux qu'on a créés et ceux dont on fait partie, pour partager des collections avec eux (#455).
import { onMounted, ref } from 'vue'
import { useGroups } from '../composables/useGroups'
import GroupMembersPanel from './GroupMembersPanel.vue'

const { groups, isLoading, groupError, refreshGroups, createGroup } = useGroups()

const newName = ref('')
const openId = ref<string | null>(null)

onMounted(refreshGroups)

async function submit() {
  const name = newName.value.trim()
  if (!name) return
  const group = await createGroup(name)
  if (group) {
    newName.value = ''
    openId.value = group.id
  }
}

function toggle(id: string) {
  openId.value = openId.value === id ? null : id
}

function role(group: { isOwner: boolean; canManage: boolean; source: string }): string {
  if (group.source !== 'muffin') return "Copié d'Open WebUI"
  if (group.isOwner) return 'Propriétaire'
  // Not its owner but may manage it: an administrator, who sees every group.
  return group.canManage ? 'Administrateur' : 'Membre'
}
</script>

<template>
  <section class="groups-view">
    <h1>Mes groupes</h1>
    <p class="groups-view__intro">
      Un groupe réunit des personnes avec qui partager des collections, sans passer par Keycloak. Tout le monde peut en créer :
      vous en êtes propriétaire et vous gérez ses membres. Les groupes copiés d'Open WebUI se voient ici mais ne se modifient
      pas.
    </p>

    <form class="groups-view__create" @submit.prevent="submit">
      <label class="fr-label" for="new-group-name">Nouveau groupe</label>
      <div class="groups-view__row">
        <input id="new-group-name" v-model="newName" class="fr-input" type="text" maxlength="120" placeholder="Nom du groupe" />
        <button type="submit" class="fr-btn" :disabled="!newName.trim()">Créer</button>
      </div>
    </form>
    <p v-if="groupError && !openId" class="groups-view__error" role="alert">{{ groupError }}</p>

    <p v-if="isLoading && !groups.length" class="groups-view__empty">Chargement…</p>
    <p v-else-if="!groups.length" class="groups-view__empty">Vous n'avez aucun groupe pour l'instant.</p>

    <ul v-else class="groups-view__list">
      <li v-for="group in groups" :key="group.id" class="groups-view__item">
        <div class="groups-view__head">
          <div class="groups-view__text">
            <strong>{{ group.name }}</strong>
            <span v-if="group.description" class="groups-view__description">{{ group.description }}</span>
          </div>
          <span class="groups-view__badge">{{ role(group) }}</span>
          <span class="groups-view__count">
            {{ group.memberCount }} membre{{ group.memberCount > 1 ? 's' : '' }}
            <template v-if="group.pendingCount"> · {{ group.pendingCount }} invité{{ group.pendingCount > 1 ? 's' : '' }}</template>
          </span>
          <button
            v-if="group.canManage"
            type="button"
            class="fr-btn fr-btn--sm fr-btn--secondary"
            :aria-expanded="openId === group.id"
            @click="toggle(group.id)"
          >
            {{ openId === group.id ? 'Fermer' : 'Gérer' }}
          </button>
        </div>
        <GroupMembersPanel v-if="openId === group.id" :group="group" @deleted="openId = null" />
      </li>
    </ul>
  </section>
</template>

<style scoped>
.groups-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.groups-view > * {
  max-width: 48rem;
  margin-left: auto;
  margin-right: auto;
}

.groups-view__create {
  margin-top: 1.5rem;
}

.groups-view__row {
  display: flex;
  gap: 0.5rem;
}

.groups-view__row input {
  flex: 1;
  min-width: 0;
}

.groups-view__list {
  list-style: none;
  margin-top: 1.5rem;
  margin-bottom: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.groups-view__item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
}

.groups-view__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.groups-view__text {
  flex: 1;
  min-width: 10rem;
  display: flex;
  flex-direction: column;
}

.groups-view__description,
.groups-view__count {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.groups-view__badge {
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--background-contrast-grey);
}

.groups-view__empty {
  margin-top: 1.5rem;
  color: var(--text-mention-grey);
}

.groups-view__error {
  color: var(--text-default-error);
}
</style>
