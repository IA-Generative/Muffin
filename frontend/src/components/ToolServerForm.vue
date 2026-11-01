<script setup lang="ts">
// Ajouter ou modifier un serveur MCP : son adresse (publique), son accès, et qui peut utiliser ses outils.
import { computed, reactive } from 'vue'
import { useCurrentUser } from '../composables/useCurrentUser'
import { useTools } from '../composables/useTools'
import type { ToolServer, ToolServerDraft } from '../types/tool'

const props = defineProps<{ server: ToolServer | null }>()
const emit = defineEmits<{ saved: [server: ToolServer]; cancel: [] }>()

const { saveServer, toolError } = useTools()
const { user } = useCurrentUser()

const draft = reactive<ToolServerDraft>({
  name: props.server?.name ?? '',
  url: props.server?.url ?? '',
  authMode: props.server?.authMode ?? 'none',
  token: '',
  visibility: props.server?.visibility ?? 'private',
  groupIds: [...(props.server?.groupIds ?? [])],
})

// On ne partage qu'avec les groupes dont on fait partie.
const myGroups = computed(() => user.value?.groups ?? [])
const missingToken = computed(() => draft.authMode === 'bearer' && !draft.token && !props.server?.hasToken)
const problems = computed(() => {
  const list: string[] = []
  if (!draft.name.trim()) list.push('Donnez un nom au serveur.')
  if (!/^https?:\/\//i.test(draft.url.trim())) list.push('L’adresse doit commencer par http:// ou https://.')
  if (missingToken.value) list.push('Ce serveur demande un jeton.')
  if (draft.visibility === 'groups' && !draft.groupIds.length) list.push('Choisissez au moins un groupe.')
  return list
})

async function submit() {
  if (problems.value.length) return
  const saved = await saveServer(draft, props.server?.id)
  if (saved) emit('saved', saved)
}
</script>

<template>
  <form class="tool-form" @submit.prevent="submit">
    <div class="fr-input-group">
      <label class="fr-label" for="tool-name">Nom</label>
      <input id="tool-name" v-model="draft.name" class="fr-input" maxlength="100" required placeholder="Dossiers RH" />
    </div>

    <div class="fr-input-group">
      <label class="fr-label" for="tool-url">
        Adresse du serveur MCP
        <span class="fr-hint-text">
          Une adresse publique (http ou https), sans identifiant dedans. Une adresse du réseau interne est refusée.
        </span>
      </label>
      <input id="tool-url" v-model="draft.url" class="fr-input" type="url" required placeholder="https://outils.exemple.fr/mcp" />
    </div>

    <fieldset class="tool-form__fieldset">
      <legend class="fr-label">Accès</legend>
      <div class="fr-radio-group">
        <input id="auth-none" v-model="draft.authMode" type="radio" value="none" />
        <label class="fr-label" for="auth-none">Sans authentification</label>
      </div>
      <div class="fr-radio-group">
        <input id="auth-bearer" v-model="draft.authMode" type="radio" value="bearer" />
        <label class="fr-label" for="auth-bearer">
          Avec un jeton
          <span class="fr-hint-text">Gardé chiffré, utilisé pour appeler le serveur, jamais affiché ensuite.</span>
        </label>
      </div>
      <div v-if="draft.authMode === 'bearer'" class="fr-input-group">
        <label class="fr-label" for="tool-token">
          Jeton <span v-if="server?.hasToken" class="fr-hint-text">Laisser vide pour garder celui qui est enregistré.</span>
        </label>
        <input id="tool-token" v-model="draft.token" class="fr-input" type="password" autocomplete="off" />
      </div>
    </fieldset>

    <fieldset class="tool-form__fieldset">
      <legend class="fr-label">Qui peut utiliser ses outils</legend>
      <div class="fr-radio-group">
        <input id="vis-private" v-model="draft.visibility" type="radio" value="private" />
        <label class="fr-label" for="vis-private">Moi seul</label>
      </div>
      <div class="fr-radio-group">
        <input id="vis-groups" v-model="draft.visibility" type="radio" value="groups" />
        <label class="fr-label" for="vis-groups">Les membres de certains de mes groupes</label>
      </div>
      <ul v-if="draft.visibility === 'groups'" class="tool-form__choices">
        <li v-for="group in myGroups" :key="group" class="fr-checkbox-group">
          <input :id="`tool-group-${group}`" v-model="draft.groupIds" type="checkbox" :value="group" />
          <label class="fr-label" :for="`tool-group-${group}`">{{ group }}</label>
        </li>
        <li v-if="!myGroups.length" class="tool-form__hint">Vous ne faites partie d’aucun groupe.</li>
      </ul>
      <div class="fr-radio-group">
        <input id="vis-all" v-model="draft.visibility" type="radio" value="all" />
        <label class="fr-label" for="vis-all">Toute l’organisation</label>
      </div>
      <p class="tool-form__hint">
        Chaque personne appelle le serveur avec son propre quota, et ne voit de lui que son nom et son adresse d’origine.
      </p>
    </fieldset>

    <ul v-if="problems.length" class="tool-form__problems" role="alert">
      <li v-for="problem in problems" :key="problem">{{ problem }}</li>
    </ul>
    <p v-if="toolError" class="tool-form__problems" role="alert">{{ toolError }}</p>

    <div class="tool-form__actions">
      <button type="submit" class="fr-btn" :disabled="problems.length > 0">
        {{ server ? 'Enregistrer' : 'Ajouter et importer les outils' }}
      </button>
      <button type="button" class="fr-btn fr-btn--secondary" @click="emit('cancel')">Annuler</button>
    </div>
  </form>
</template>

<style scoped>
.tool-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.tool-form__fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.tool-form__choices {
  list-style: none;
  margin: 0;
  padding: 0 0 0 1.5rem;
}

.tool-form__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.tool-form__problems {
  margin: 0;
  padding-left: 1.25rem;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.tool-form__actions {
  display: flex;
  gap: 0.5rem;
}
</style>
