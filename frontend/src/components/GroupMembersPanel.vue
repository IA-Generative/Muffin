<script setup lang="ts">
// Gérer un groupe : le renommer, voir qui y est et qui est invité, ajouter par email, le supprimer.
// Un membre ne voit ici que le nombre de personnes (le serveur ne lui donne pas la liste).
import { onMounted, ref } from 'vue'
import { useGroups } from '../composables/useGroups'
import type { Group, GroupMember } from '../types/group'

const props = defineProps<{ group: Group }>()
const emit = defineEmits<{ deleted: [] }>()

const { updateGroup, deleteGroup, fetchMembers, addMember, removeMember, groupError } = useGroups()

const members = ref<GroupMember[]>([])
const name = ref(props.group.name)
const description = ref(props.group.description)
const email = ref('')

async function loadMembers() {
  members.value = await fetchMembers(props.group.id)
}
onMounted(loadMembers)

async function saveDetails() {
  if (!name.value.trim()) return
  await updateGroup(props.group.id, { name: name.value.trim(), description: description.value.trim() })
}

async function submitMember() {
  if (!email.value.trim()) return
  if (await addMember(props.group.id, email.value.trim())) {
    email.value = ''
    await loadMembers()
  }
}

async function take(member: GroupMember) {
  if (await removeMember(props.group.id, member.id)) await loadMembers()
}

async function remove() {
  if (
    !confirm(
      `Supprimer le groupe « ${props.group.name} » ? Ses membres le perdent, et les collections partagées avec lui ne le sont plus.`,
    )
  )
    return
  if (await deleteGroup(props.group.id)) emit('deleted')
}
</script>

<template>
  <div class="members">
    <form class="members__details" @submit.prevent="saveDetails">
      <label class="fr-label" :for="`group-name-${group.id}`">Nom</label>
      <input :id="`group-name-${group.id}`" v-model="name" class="fr-input" type="text" maxlength="120" />
      <label class="fr-label" :for="`group-description-${group.id}`">Description</label>
      <input :id="`group-description-${group.id}`" v-model="description" class="fr-input" type="text" maxlength="1000" />
      <div class="members__actions">
        <button type="submit" class="fr-btn fr-btn--sm" :disabled="!name.trim()">Enregistrer</button>
        <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" @click="remove">Supprimer le groupe</button>
      </div>
    </form>

    <h3 class="members__title">Membres</h3>
    <ul v-if="members.length" class="members__list">
      <li v-for="member in members" :key="member.id" class="members__item">
        <span class="members__who">{{ member.display }}</span>
        <span class="members__status" :class="`members__status--${member.status}`">
          {{ member.status === 'pending' ? 'Invité' : 'Membre' }}
        </span>
        <button
          type="button"
          class="fr-btn fr-btn--sm fr-btn--tertiary-no-outline"
          :aria-label="`Retirer ${member.display} du groupe`"
          @click="take(member)"
        >
          Retirer
        </button>
      </li>
    </ul>
    <p v-else class="members__hint">Personne dans ce groupe pour l'instant.</p>

    <form class="members__add" @submit.prevent="submitMember">
      <label class="fr-label" :for="`group-member-${group.id}`">Ajouter quelqu'un par son email</label>
      <div class="members__row">
        <input
          :id="`group-member-${group.id}`"
          v-model="email"
          class="fr-input"
          type="email"
          placeholder="personne@exemple.fr"
        />
        <button type="submit" class="fr-btn fr-btn--sm" :disabled="!email.trim()">Inviter</button>
      </div>
      <p class="members__hint">
        Aucune vérification n'est faite : la personne devient membre à sa prochaine connexion, qu'elle ait déjà un compte
        ou non. Retirer un membre ou supprimer le groupe retire l'accès aux collections partagées avec lui.
      </p>
    </form>
    <p v-if="groupError" class="members__error" role="alert">{{ groupError }}</p>
  </div>
</template>

<style scoped>
.members {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
}

.members__details {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.members__actions,
.members__row {
  display: flex;
  gap: 0.5rem;
}

.members__row input {
  flex: 1;
  min-width: 0;
}

.members__title {
  margin: 0.5rem 0 0;
  font-size: 1rem;
}

.members__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.members__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.members__who {
  flex: 1;
  font-size: 0.8125rem;
}

.members__status {
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--background-contrast-grey);
}

.members__hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.members__error {
  margin: 0;
  color: var(--text-default-error);
}
</style>
