<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { usePrompts } from '../composables/usePrompts'

const props = defineProps<{
  name: string
  activeVersion: { version: number; content: string; created_at: string } | null
}>()

const { versionsByName, fetchVersions, createVersion, activateVersion } = usePrompts()

// null = viewing/editing the active version (the only editable state). A number = read-only
// view of that past version - old versions are immutable, editing always creates a new one.
const selectedVersion = ref<number | null>(null)
const draft = ref(props.activeVersion?.content ?? '')
const publishing = ref(false)
const published = ref(false)
const rollingBack = ref(false)

const versions = computed(() => versionsByName.value[props.name] ?? [])
// Derived from the fetched history, not the `activeVersion` prop: the parent's summary list
// (usePrompts().summaries) is only fetched once on page load, so it goes stale the moment this
// card publishes or rolls back a version. `versions` is refetched locally after every mutation
// (see publish/rollback below), so it's always the source of truth for what's active now.
const currentActive = computed(() => versions.value.find((v) => v.is_active) ?? props.activeVersion)
const viewedVersion = computed(() =>
  selectedVersion.value === null ? null : versions.value.find((v) => v.version === selectedVersion.value),
)
const isViewingPast = computed(() => selectedVersion.value !== null)

onMounted(() => fetchVersions(props.name))

watch(
  currentActive,
  (value) => {
    if (value && selectedVersion.value === null) draft.value = value.content
  },
  { immediate: true },
)

function selectVersion(version: number | null) {
  selectedVersion.value = version
  draft.value = version === null ? currentActive.value?.content ?? '' : (viewedVersion.value?.content ?? '')
}

async function publish() {
  if (!draft.value.trim()) return
  publishing.value = true
  const created = await createVersion(props.name, draft.value)
  if (created) {
    await fetchVersions(props.name)
    const latest = versionsByName.value[props.name]?.[0]
    if (latest) await activateVersion(props.name, latest.version)
    await fetchVersions(props.name)
    published.value = true
    setTimeout(() => (published.value = false), 2000)
  }
  publishing.value = false
}

async function rollback() {
  if (selectedVersion.value === null) return
  rollingBack.value = true
  await activateVersion(props.name, selectedVersion.value)
  await fetchVersions(props.name)
  selectVersion(null)
  rollingBack.value = false
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
      <span v-if="currentActive" class="prompt-editor__badge">v{{ currentActive.version }} active</span>
      <span v-else class="prompt-editor__badge prompt-editor__badge--none">Aucune version active</span>

      <label class="prompt-editor__version-picker">
        <span class="prompt-editor__version-picker-label">Version</span>
        <select
          class="fr-select"
          :value="selectedVersion ?? 'active'"
          @change="selectVersion(($event.target as HTMLSelectElement).value === 'active' ? null : Number(($event.target as HTMLSelectElement).value))"
        >
          <option value="active">Actuelle (éditable) - v{{ currentActive?.version ?? '?' }}</option>
          <option v-for="version in versions.filter((v) => !v.is_active)" :key="version.id" :value="version.version">
            v{{ version.version }} - {{ formatDate(version.created_at) }}
          </option>
        </select>
      </label>
    </div>

    <p v-if="isViewingPast" class="prompt-editor__readonly-hint">
      Version passée en lecture seule (v{{ selectedVersion }}, {{ formatDate(viewedVersion?.created_at ?? '') }}) -
      les anciennes versions ne peuvent pas être modifiées. Revenez à la version actuelle pour éditer, ou activez
      celle-ci pour en faire la nouvelle version courante.
    </p>

    <textarea
      v-model="draft"
      class="prompt-editor__textarea fr-input"
      :class="{ 'prompt-editor__textarea--readonly': isViewingPast }"
      :aria-label="`Contenu du prompt ${name}`"
      :readonly="isViewingPast"
      rows="6"
    />

    <div class="prompt-editor__footer">
      <span v-if="published" class="prompt-editor__saved">Publié</span>
      <button
        v-if="isViewingPast"
        type="button"
        class="fr-btn fr-btn--sm"
        :disabled="rollingBack"
        @click="rollback"
      >
        {{ rollingBack ? 'Activation…' : 'Revenir à cette version' }}
      </button>
      <button
        v-else
        type="button"
        class="fr-btn fr-btn--sm"
        :disabled="!draft.trim() || publishing"
        @click="publish"
      >
        {{ publishing ? 'Publication…' : 'Publier cette version' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.prompt-editor {
  padding: 1.25rem;
}

.prompt-editor__header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
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

.prompt-editor__version-picker {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.prompt-editor__version-picker select {
  font-size: 0.8125rem;
  padding: 0.25rem 0.5rem;
}

.prompt-editor__readonly-hint {
  margin: 0 0 0.625rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
  font-size: 0.8125rem;
}

.prompt-editor__textarea {
  width: 100%;
  box-sizing: border-box;
  font-family: 'Consolas', monospace;
  font-size: 0.8125rem;
  resize: vertical;
}

.prompt-editor__textarea--readonly {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
  cursor: default;
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
</style>
