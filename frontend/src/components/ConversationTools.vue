<script setup lang="ts">
// Les outils de la conversation (#343) : ce que le chat peut appeler, et ce qu'on lui retire pour cette conversation. On ne
// peut que retirer : un outil qu'on n'a pas le droit d'utiliser n'apparaît pas.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChat } from '../composables/useChat'
import { useToolSearch } from '../composables/useToolSearch'
import { useTools } from '../composables/useTools'

const router = useRouter()
const { activeId, isConversationSaved } = useChat()
const { tools, refreshTools, setConversationTools } = useTools()

const open = ref(false)
const wrapper = ref<HTMLElement>()
const saved = computed(() => isConversationSaved(activeId.value))
// Tous les outils que la personne peut utiliser : celui qui modifie des données aussi, que l'assistant propose et qu'elle autorise.
const usable = computed(() => tools.value)
const active = computed(() => usable.value.filter((tool) => tool.available).length)
// Chercher un outil par ce qu'il fait (#530), les plus proches d'abord ; les retirés restent trouvables pour être remis.
const { query, results, active: searching, loading } = useToolSearch(
  usable,
  computed(() => (saved.value ? activeId.value : undefined)),
)

function outside(event: MouseEvent) {
  if (open.value && !wrapper.value?.contains(event.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', outside))
onBeforeUnmount(() => document.removeEventListener('click', outside))

// Rechargé quand on ouvre le menu et quand on change de conversation : ce qui est retiré dépend d'elle.
watch([open, activeId], () => {
  if (open.value) refreshTools(saved.value ? activeId.value : undefined)
})

async function toggle(ref_: string, on: boolean) {
  if (!saved.value) return
  const removed = new Set(tools.value.filter((tool) => !tool.available && tool.reason?.startsWith('retiré')).map((tool) => tool.ref))
  if (on) removed.delete(ref_)
  else removed.add(ref_)
  await setConversationTools(activeId.value, [...removed])
}
</script>

<template>
  <div ref="wrapper" class="conversation-tools">
    <button type="button" class="conversation-tools__trigger" aria-haspopup="menu" :aria-expanded="open" @click="open = !open">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11.4 15.2 3.7 22.9 1.1 20.3l7.7-7.7M14 2a5 5 0 0 0-4.4 7.3L8 11l5 5 1.7-1.6A5 5 0 1 0 14 2z" />
      </svg>
      <span>Outils<template v-if="usable.length"> ({{ active }}/{{ usable.length }})</template></span>
    </button>

    <div v-if="open" class="conversation-tools__menu" role="menu">
      <p v-if="!saved" class="conversation-tools__hint">
        Vous pourrez retirer des outils pour cette conversation après votre premier message.
      </p>
      <div v-if="usable.length > 6" class="conversation-tools__search" role="search">
        <label class="fr-label" for="conv-tools-search">Chercher un outil</label>
        <input
          id="conv-tools-search"
          v-model="query"
          type="search"
          class="fr-input fr-input--sm"
          placeholder="Ce qu’il fait…"
          autocomplete="off"
        />
      </div>
      <p v-if="searching && loading" class="conversation-tools__hint" role="status">Recherche…</p>
      <p v-else-if="searching && !results.length" class="conversation-tools__hint" role="status">
        Aucun outil ne correspond à « {{ query.trim() }} ».
      </p>
      <ul class="conversation-tools__list">
        <li v-for="tool in results" :key="tool.ref" class="fr-checkbox-group">
          <input
            :id="`conv-tool-${tool.ref}`"
            type="checkbox"
            :checked="tool.available"
            :disabled="!saved"
            @change="toggle(tool.ref, ($event.target as HTMLInputElement).checked)"
          />
          <label class="fr-label" :for="`conv-tool-${tool.ref}`">
            {{ tool.name }}<span v-if="tool.serverName" class="conversation-tools__server"> · {{ tool.serverName }}</span>
            <span v-if="tool.sideEffect" class="conversation-tools__server"> · modifie des données</span>
            <span class="fr-hint-text">{{ tool.description.slice(0, 90) }}</span>
          </label>
        </li>
      </ul>
      <button type="button" class="conversation-tools__manage" @click="router.push('/tools')">Gérer les serveurs d’outils…</button>
    </div>
  </div>
</template>

<style scoped>
.conversation-tools {
  position: relative;
}

.conversation-tools__trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font-size: 0.875rem;
  cursor: pointer;
}

.conversation-tools__menu {
  position: absolute;
  z-index: 20;
  top: calc(100% + 0.25rem);
  right: 0;
  width: 22rem;
  max-height: 24rem;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.375rem;
  background: var(--background-default-grey);
  box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
}

.conversation-tools__search {
  margin-bottom: 0.5rem;
}

.conversation-tools__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.conversation-tools__hint,
.conversation-tools__server {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.conversation-tools__server {
  margin: 0 0 0 0.25rem;
}

.conversation-tools__manage {
  margin-top: 0.5rem;
  padding: 0.375rem 0;
  border: 0;
  background: transparent;
  color: var(--text-action-high-blue-france);
  font-size: 0.875rem;
  cursor: pointer;
}
</style>
