<script setup lang="ts">
// Qui peut voir la collection : la visibilité et les partages. Ces deux réglages s'appliquent tout de suite (ils
// n'attendent pas le bouton « Enregistrer » des autres paramètres : ils ne changent pas l'indexation).
import { computed, onMounted, ref, watch } from 'vue'
import '../assets/settings-form.css'
import { useCollections } from '../composables/useCollections'
import { useCurrentUser } from '../composables/useCurrentUser'
import { useGroups } from '../composables/useGroups'
import type { Collection, SharePermission, ShareSubjectType } from '../types/collection'
import SettingsField from './SettingsField.vue'
import SettingsSection from './SettingsSection.vue'

const props = defineProps<{ collection: Collection }>()
const { updateVisibility, createShare, updateSharePermission, deleteShare, shareError } = useCollections()

// Les groupes faits dans Muffin (#455) : ceux qu'on a créés ou dont on fait partie.
const { groups: muffinGroups, refreshGroups } = useGroups()
onMounted(refreshGroups)

const visibilityDraft = ref(props.collection.visibility)
watch(
  () => [props.collection.id, props.collection.visibility] as const,
  () => {
    visibilityDraft.value = props.collection.visibility
  },
)

function applyVisibility() {
  if (visibilityDraft.value === props.collection.visibility) return
  if (
    visibilityDraft.value === 'public' &&
    !confirm(
      'Rendre cette collection publique la rend visible et cherchable par tous les utilisateurs authentifiés. Confirmer ?',
    )
  ) {
    visibilityDraft.value = props.collection.visibility
    return
  }
  updateVisibility(props.collection.id, visibilityDraft.value)
}

type ShareKind = ShareSubjectType | 'muffin-group'
const shareKind = ref<ShareKind>('user')
const sharePermission = ref<SharePermission>('read')
const shareIdentifier = ref('')
const muffinGroupId = ref('')

// Le type envoyé au serveur : un groupe de Muffin est un groupe, désigné par son id.
const shareSubjectType = computed<ShareSubjectType>(() => (shareKind.value === 'user' ? 'user' : 'group'))

// Les groupes de l'utilisateur sont proposés en liste ; « Autre groupe » garde la saisie libre
// pour un groupe dont il n'est pas membre.
const { user: currentUser } = useCurrentUser()
const myGroups = computed(() => currentUser.value?.groups ?? [])
const OTHER_GROUP = '__other__'
const groupChoice = ref(OTHER_GROUP)
const isFreeGroup = computed(() => myGroups.value.length === 0 || groupChoice.value === OTHER_GROUP)

watch(
  [shareKind, myGroups],
  () => {
    if (shareKind.value === 'group' && !myGroups.value.includes(groupChoice.value)) {
      groupChoice.value = myGroups.value[0] ?? OTHER_GROUP
    }
  },
  { immediate: true },
)

const shareTarget = computed(() => {
  if (shareKind.value === 'muffin-group') return muffinGroupId.value
  return shareKind.value === 'group' && !isFreeGroup.value ? groupChoice.value : shareIdentifier.value.trim()
})

function submitShare() {
  if (!shareTarget.value) return
  createShare(props.collection.id, {
    subjectType: shareSubjectType.value,
    ...(shareKind.value === 'muffin-group' ? { groupId: shareTarget.value } : { identifier: shareTarget.value }),
    permission: sharePermission.value,
  })
  shareIdentifier.value = ''
}

const PERMISSION_LABEL: Record<SharePermission, string> = { read: 'Lecture', write: 'Lecture et écriture' }

const SHARE_STATUS_LABEL: Record<'pending' | 'active', string> = { pending: 'En attente', active: 'Actif' }

const visibilitySummary = computed(() => (props.collection.visibility === 'public' ? 'Publique' : 'Privée'))
const sharesSummary = computed(() => {
  const count = props.collection.shares.length
  return count ? `${count} partage${count > 1 ? 's' : ''}` : 'Aucun partage'
})
</script>

<template>
  <div class="sf-stack">
    <SettingsSection title="Visibilité" :summary="visibilitySummary">
      <form class="sf-stack" @submit.prevent="applyVisibility">
        <SettingsField
          id="visibility"
          label="Qui peut voir cette collection"
          hint="Une collection publique est visible et cherchable par n'importe quel utilisateur authentifié, en lecture seule. Ses sous-collections le sont aussi."
        >
          <template #default="{ id, describedby }">
            <select :id="id" v-model="visibilityDraft" class="fr-select" :aria-describedby="describedby">
              <option value="private">Privée (vous et les personnes ou groupes invités)</option>
              <option value="public">Publique (tous les utilisateurs authentifiés)</option>
            </select>
          </template>
        </SettingsField>
        <p v-if="collection.inheritedPublicFrom && collection.visibility === 'private'" class="sf-callout">
          Cette collection est tout de même publique, car sa collection parente « {{ collection.inheritedPublicFrom.name }} »
          l'est.
        </p>
        <div class="sf-actions">
          <button type="submit" class="fr-btn fr-btn--sm" :disabled="visibilityDraft === collection.visibility">
            Appliquer
          </button>
        </div>
      </form>
    </SettingsSection>

    <SettingsSection title="Partages" :summary="sharesSummary">
      <form class="sf-stack" @submit.prevent="submitShare">
        <SettingsField id="share-subject-type" label="Inviter un utilisateur ou un groupe">
          <template #default="{ id }">
            <div class="access__share-form">
              <select :id="id" v-model="shareKind" class="fr-select" aria-label="Type de destinataire">
                <option value="user">Email</option>
                <option value="muffin-group">Groupe Muffin</option>
                <option value="group">Groupe Keycloak</option>
              </select>
              <select
                v-if="shareKind === 'muffin-group'"
                id="share-muffin-group"
                v-model="muffinGroupId"
                class="fr-select"
                aria-label="Groupe Muffin"
              >
                <option value="" disabled>Choisir un groupe…</option>
                <option v-for="group in muffinGroups" :key="group.id" :value="group.id">{{ group.name }}</option>
              </select>
              <select
                v-if="shareKind === 'group' && myGroups.length"
                id="share-group"
                v-model="groupChoice"
                class="fr-select"
                aria-label="Groupe"
              >
                <optgroup label="Vos groupes">
                  <option v-for="group in myGroups" :key="group" :value="group">{{ group }}</option>
                </optgroup>
                <option :value="OTHER_GROUP">Autre groupe (saisie libre)…</option>
              </select>
              <div class="access__share-row">
                <input
                  v-if="shareKind === 'user' || (shareKind === 'group' && isFreeGroup)"
                  id="share-identifier"
                  v-model="shareIdentifier"
                  type="text"
                  aria-label="Adresse email ou nom du groupe"
                  :placeholder="shareKind === 'user' ? 'personne@exemple.fr' : '/nom-du-groupe'"
                />
                <select v-model="sharePermission" class="fr-select access__permission" aria-label="Droit accordé">
                  <option value="read">{{ PERMISSION_LABEL.read }}</option>
                  <option value="write">{{ PERMISSION_LABEL.write }}</option>
                </select>
                <button type="submit" class="fr-btn fr-btn--sm" :disabled="!shareTarget">
                  {{ shareKind === 'muffin-group' ? 'Partager' : 'Inviter' }}
                </button>
              </div>
            </div>
          </template>
        </SettingsField>
        <p class="sf-hint">
          Un email ou un groupe Keycloak n'est pas vérifié ici : l'invitation s'active à la prochaine connexion de la
          personne ou d'un membre du groupe. Un groupe Muffin est actif tout de suite. « Lecture et écriture » permet aussi
          de modifier les documents vivants, mais pas les réglages, le partage ni la suppression, qui restent au propriétaire.
          Un partage s'applique aussi aux sous-collections.
        </p>
        <p v-if="shareError" class="sf-error" role="alert">{{ shareError }}</p>
      </form>

      <ul v-if="collection.shares.length" class="access__list">
        <li v-for="share in collection.shares" :key="share.id" class="access__item">
          <span class="access__who">{{ share.displayHint }}</span>
          <span v-if="share.inheritedFrom" class="access__inherited">Hérité de « {{ share.inheritedFrom.name }} »</span>
          <select
            v-if="!share.inheritedFrom"
            class="fr-select access__permission"
            :value="share.permission"
            :aria-label="`Droit de ${share.displayHint}`"
            @change="
              updateSharePermission(collection.id, share.id, ($event.target as HTMLSelectElement).value as SharePermission)
            "
          >
            <option value="read">{{ PERMISSION_LABEL.read }}</option>
            <option value="write">{{ PERMISSION_LABEL.write }}</option>
          </select>
          <span v-else class="access__inherited-permission">{{ PERMISSION_LABEL[share.permission] }}</span>
          <span class="access__status" :class="`access__status--${share.status}`">
            {{ SHARE_STATUS_LABEL[share.status] }}
          </span>
          <button
            v-if="!share.inheritedFrom"
            type="button"
            class="fr-btn fr-btn--sm fr-btn--tertiary-no-outline"
            :aria-label="`Révoquer le partage avec ${share.displayHint}`"
            @click="deleteShare(collection.id, share.id)"
          >
            Révoquer
          </button>
        </li>
      </ul>
      <p v-else class="sf-hint">Aucun partage sur cette collection.</p>
    </SettingsSection>
  </div>
</template>

<style scoped>
.access__share-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.access__share-row {
  display: flex;
  gap: 0.5rem;
}

.access__share-row input {
  flex: 1;
  min-width: 0;
}

.access__permission {
  width: auto;
  flex-shrink: 0;
}

.access__inherited-permission {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.access__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.access__item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  border-radius: 0.375rem;
  background: var(--background-alt-grey);
}

.access__who {
  flex: 1;
  font-size: 0.8125rem;
  font-family: monospace;
}

/* On its own line under the identifier, so the status and the revoke action keep their place. */
.access__inherited {
  flex-basis: 100%;
  order: 3;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.access__status {
  flex-shrink: 0;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.6875rem;
  font-weight: 700;
}

.access__status--pending {
  background: var(--background-alt-orange-terre-battue, var(--background-alt-grey));
  color: var(--text-default-grey);
}

.access__status--active {
  background: var(--background-alt-green-emeraude, var(--background-alt-grey));
  color: var(--text-default-success, var(--text-default-grey));
}
</style>
