<script setup lang="ts">
import { ref, watch } from 'vue'
import { usePrompts } from '../composables/usePrompts'

const props = defineProps<{
  name: string
  activeVersion: { version: number; content: string; created_at: string } | null
}>()

const { versionsByName, fetchVersions, createVersion, activateVersion } = usePrompts()

const draft = ref(props.activeVersion?.content ?? '')
watch(
  () => props.activeVersion,
  (value) => {
    if (value) draft.value = value.content
  },
)

const showHistory = ref(false)
const publishing = ref(false)
const published = ref(false)
const activatingVersion = ref<number | null>(null)

async function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) await fetchVersions(props.name)
}

async function publish() {
  if (!draft.value.trim()) return
  publishing.value = true
  const created = await createVersion(props.name, draft.value)
  if (created) {
    // Newly created version is always max+1 for this name - re-fetch to know its number,
    // then activate it so "publier" means "this is now live", not just "saved as a draft".
    await fetchVersions(props.name)
    const latest = versionsByName.value[props.name]?.[0]
    if (latest) await activateVersion(props.name, latest.version)
    if (showHistory.value) await fetchVersions(props.name)
    published.value = true
    setTimeout(() => (published.value = false), 2000)
  }
  publishing.value = false
}

async function rollback(version: number) {
  activatingVersion.value = version
  await activateVersion(props.name, version)
  await fetchVersions(props.name)
  activatingVersion.value = null
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <div class="prompt-editor">
    <div class="prompt-editor__header">
      <h3 class="prompt-editor__name">{{ name }}</h3>
      <span v-if="activeVersion" class="prompt-editor__badge">v{{ activeVersion.version }} active</span>
      <span v-else class="prompt-editor__badge prompt-editor__badge--none">Aucune version active</span>
    </div>

    <textarea v-model="draft" class="prompt-editor__textarea fr-input" rows="6" />

    <div class="prompt-editor__footer">
      <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="toggleHistory">
        {{ showHistory ? "Masquer l'historique" : "Voir l'historique" }}
      </button>
      <span v-if="published" class="prompt-editor__saved">Publié</span>
      <button
        type="button"
        class="fr-btn fr-btn--sm"
        :disabled="!draft.trim() || publishing"
        @click="publish"
      >
        {{ publishing ? 'Publication…' : 'Publier cette version' }}
      </button>
    </div>

    <ul v-if="showHistory" class="prompt-editor__history">
      <li v-for="version in versionsByName[name] ?? []" :key="version.id" class="prompt-editor__history-item">
        <div class="prompt-editor__history-info">
          <span class="prompt-editor__history-version">v{{ version.version }}</span>
          <span class="prompt-editor__history-date">{{ formatDate(version.created_at) }}</span>
          <span v-if="version.is_active" class="prompt-editor__badge">active</span>
        </div>
        <button
          v-if="!version.is_active"
          type="button"
          class="fr-btn fr-btn--tertiary fr-btn--sm"
          :disabled="activatingVersion === version.version"
          @click="rollback(version.version)"
        >
          {{ activatingVersion === version.version ? 'Activation…' : 'Revenir à cette version' }}
        </button>
      </li>
      <li v-if="(versionsByName[name] ?? []).length === 0" class="prompt-editor__history-empty">
        Aucun historique.
      </li>
    </ul>
  </div>
</template>

<style scoped>
.prompt-editor {
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.prompt-editor + .prompt-editor {
  margin-top: 1rem;
}

.prompt-editor__header {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-bottom: 0.75rem;
}

.prompt-editor__name {
  margin: 0;
  font-size: 0.9375rem;
  font-family: 'Consolas', monospace;
}

.prompt-editor__badge {
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  background: var(--background-success-default);
  color: var(--text-inverted-default);
}

.prompt-editor__badge--none {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.prompt-editor__textarea {
  width: 100%;
  box-sizing: border-box;
  font-family: 'Consolas', monospace;
  font-size: 0.8125rem;
  resize: vertical;
}

.prompt-editor__footer {
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.prompt-editor__saved {
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.prompt-editor__history {
  list-style: none;
  margin: 0.75rem 0 0;
  padding: 0.75rem 0 0;
  border-top: 1px solid var(--border-default-grey);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.prompt-editor__history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.prompt-editor__history-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8125rem;
}

.prompt-editor__history-version {
  font-weight: 600;
}

.prompt-editor__history-date {
  color: var(--text-mention-grey);
}

.prompt-editor__history-empty {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}
</style>
