<script setup lang="ts">
// Le choix d'un profil (rapide, équilibré, précis) : trois cartes, chacune avec ce qu'elle règle, ce qu'elle fait
// perdre et ce qu'elle coûte pour un document de 900 pages - calculé par le backend avec les réglages du profil.
import { onMounted, reactive } from 'vue'
import '../assets/settings-form.css'
import { useCollections } from '../composables/useCollections'
import { PROFILES, type Profile, type ProfileId } from '../utils/collectionProfiles'
import { toPayload, type LongDocumentsDraft } from '../utils/longDocuments'

const props = defineProps<{
  // Le profil que les réglages actuels réalisent, null s'ils sont personnalisés.
  selected: ProfileId | null
  collectionId: string
  // Les réglages actuels : un profil ne remplace que ce qu'il règle (le seuil, par exemple, reste).
  longDocs: LongDocumentsDraft
  groupName: string
}>()
const emit = defineEmits<{ choose: [profile: Profile] }>()

const { estimateIndexing } = useCollections()
const PAGES = 900
const calls = reactive<Record<string, number | null>>({})

onMounted(() => {
  for (const profile of PROFILES) {
    const long = { ...props.longDocs, ...profile.longDocs, separateEnds: false }
    estimateIndexing(props.collectionId, PAGES, toPayload(long), profile.chunkingStrategy).then((result) => {
      calls[profile.id] = 'estimate' in result ? result.estimate.chat.total : null
    })
  }
})
</script>

<template>
  <fieldset class="profiles">
    <legend class="sr-only">Profil de la collection</legend>
    <label
      v-for="profile in PROFILES"
      :key="profile.id"
      class="profiles__card"
      :class="{ 'profiles__card--selected': selected === profile.id }"
    >
      <input
        type="radio"
        class="profiles__radio"
        :name="groupName"
        :value="profile.id"
        :checked="selected === profile.id"
        @change="emit('choose', profile)"
      />
      <span class="profiles__head">
        <span class="profiles__label">{{ profile.label }}</span>
        <span v-if="profile.recommended" class="sf-badge sf-badge--recommended">Recommandé</span>
      </span>
      <span class="profiles__tagline">{{ profile.tagline }}</span>
      <ul class="profiles__details">
        <li v-for="detail in profile.details" :key="detail">{{ detail }}</li>
      </ul>
      <span class="profiles__tradeoff">{{ profile.tradeOff }}</span>
      <span class="profiles__calls">
        <template v-if="calls[profile.id] != null">Environ {{ calls[profile.id] }} appels au modèle pour 900 pages</template>
        <template v-else>&nbsp;</template>
      </span>
    </label>
    <p v-if="selected === null" class="sf-hint profiles__custom">
      Vos réglages ne correspondent à aucun profil : ils sont personnalisés. Choisir un profil les remplace pour le
      découpage et les longs documents.
    </p>
  </fieldset>
</template>

<style scoped>
.profiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  border: 0;
}

.profiles__card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  cursor: pointer;
}

.profiles__card:hover {
  border-color: var(--border-active-blue-france);
}

.profiles__card:focus-within {
  outline: 2px solid var(--border-active-blue-france);
  outline-offset: 2px;
}

.profiles__card--selected {
  border-color: var(--border-active-blue-france);
  box-shadow: inset 0 0 0 1px var(--border-active-blue-france);
  background: var(--background-alt-blue-france);
}

.profiles__radio {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.profiles__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.profiles__label {
  font-size: 1rem;
  font-weight: 700;
}

.profiles__tagline {
  font-size: 0.875rem;
}

.profiles__details {
  margin: 0;
  padding-left: 1.125rem;
  font-size: 0.8125rem;
}

.profiles__tradeoff {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.profiles__calls {
  margin-top: auto;
  font-size: 0.8125rem;
  font-weight: 700;
}

.profiles__custom {
  grid-column: 1 / -1;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
