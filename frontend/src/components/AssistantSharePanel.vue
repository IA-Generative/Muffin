<script setup lang="ts">
// Qui peut utiliser un assistant : la visibilité et les partages, comme pour une collection. Partager un assistant ne partage
// jamais ses collections : chacun n'interroge que celles qu'il peut lire lui-même.
import { onMounted, ref } from 'vue'
import { useAssistants } from '../composables/useAssistants'
import { useGroups } from '../composables/useGroups'
import type { Assistant, AssistantShare, SharePermission } from '../types/assistant'

const props = defineProps<{ assistant: Assistant }>()

const { assistantError, setVisibility, fetchShares, createShare, updateSharePermission, deleteShare } = useAssistants()
const { groups: muffinGroups, refreshGroups } = useGroups()

const shares = ref<AssistantShare[]>([])
const kind = ref<'user' | 'group' | 'muffin-group'>('user')
const identifier = ref('')
const groupId = ref('')
const permission = ref<SharePermission>('read')

async function load() {
  shares.value = await fetchShares(props.assistant.id)
}

onMounted(() => {
  load()
  refreshGroups()
})

async function invite() {
  const ok = await createShare(props.assistant.id, {
    subjectType: kind.value === 'user' ? 'user' : 'group',
    identifier: kind.value === 'muffin-group' ? undefined : identifier.value,
    groupId: kind.value === 'muffin-group' ? groupId.value : undefined,
    permission: permission.value,
  })
  if (ok) {
    identifier.value = ''
    await load()
  }
}

async function changePermission(share: AssistantShare, value: SharePermission) {
  if (await updateSharePermission(props.assistant.id, share.id, value)) share.permission = value
}

async function revoke(share: AssistantShare) {
  if (await deleteShare(props.assistant.id, share.id)) await load()
}

async function togglePublic(event: Event) {
  const makePublic = (event.target as HTMLInputElement).checked
  if (
    makePublic &&
    !confirm('Rendre cet assistant public le rend utilisable par tous les utilisateurs de l’organisation. Confirmer ?')
  ) {
    ;(event.target as HTMLInputElement).checked = false
    return
  }
  if (!(await setVisibility(props.assistant.id, makePublic ? 'public' : 'private'))) {
    ;(event.target as HTMLInputElement).checked = !makePublic
  }
}
</script>

<template>
  <section class="assistant-share" aria-label="Partage de l’assistant">
    <p class="assistant-share__note">
      Partager un assistant ne partage <strong>pas</strong> ses collections : chaque personne n’interroge que celles qu’elle peut
      déjà lire. Une collection qui ne lui est pas accessible est ignorée, et elle en est prévenue.
    </p>

    <div class="fr-checkbox-group">
      <input id="assistant-public" type="checkbox" :checked="assistant.visibility === 'public'" @change="togglePublic" />
      <label class="fr-label" for="assistant-public">
        Public dans l’organisation
        <span class="fr-hint-text">Réservé aux administrateurs, sauf réglage du serveur.</span>
      </label>
    </div>

    <form class="assistant-share__form" @submit.prevent="invite">
      <div class="assistant-share__row">
        <select v-model="kind" class="fr-select" aria-label="Partager avec">
          <option value="user">Une personne (email)</option>
          <option value="group">Un groupe Keycloak</option>
          <option v-if="muffinGroups.length" value="muffin-group">Un de mes groupes</option>
        </select>
        <select v-if="kind === 'muffin-group'" v-model="groupId" class="fr-select" aria-label="Groupe">
          <option value="" disabled>Choisir un groupe</option>
          <option v-for="group in muffinGroups" :key="group.id" :value="group.id">{{ group.name }}</option>
        </select>
        <input
          v-else
          v-model="identifier"
          class="fr-input"
          :type="kind === 'user' ? 'email' : 'text'"
          :placeholder="kind === 'user' ? 'prenom.nom@exemple.fr' : '/RH'"
          :aria-label="kind === 'user' ? 'Email' : 'Groupe'"
        />
        <select v-model="permission" class="fr-select" aria-label="Droit">
          <option value="read">Utiliser</option>
          <option value="write">Utiliser et modifier</option>
        </select>
        <button
          type="submit"
          class="fr-btn fr-btn--sm"
          :disabled="kind === 'muffin-group' ? !groupId : !identifier.trim()"
        >
          Partager
        </button>
      </div>
      <p v-if="assistantError" class="assistant-share__error" role="alert">{{ assistantError }}</p>
    </form>

    <ul v-if="shares.length" class="assistant-share__list">
      <li v-for="share in shares" :key="share.id" class="assistant-share__item">
        <span class="assistant-share__who">
          {{ share.subjectType === 'group' ? 'Groupe' : 'Personne' }} · {{ share.displayHint }}
          <em v-if="share.status === 'pending'">invitation en attente de sa connexion</em>
        </span>
        <select
          class="fr-select assistant-share__permission"
          :value="share.permission"
          :aria-label="`Droit de ${share.displayHint}`"
          @change="changePermission(share, ($event.target as HTMLSelectElement).value as SharePermission)"
        >
          <option value="read">Utiliser</option>
          <option value="write">Utiliser et modifier</option>
        </select>
        <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="revoke(share)">Retirer</button>
      </li>
    </ul>
    <p v-else class="assistant-share__empty">Pas encore partagé.</p>
  </section>
</template>

<style scoped>
.assistant-share {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-default-grey);
}

.assistant-share__note,
.assistant-share__empty {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.assistant-share__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.assistant-share__row .fr-input {
  flex: 1;
  min-width: 10rem;
}

.assistant-share__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.assistant-share__item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.assistant-share__who {
  flex: 1;
  min-width: 10rem;
  font-size: 0.875rem;
}

.assistant-share__who em {
  margin-left: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.assistant-share__permission {
  width: auto;
}

.assistant-share__error {
  margin: 0.5rem 0 0;
  color: var(--text-default-error);
}
</style>
