<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useCguAdmin } from '../composables/useCguAdmin'

const { versions, fetchVersions, createVersion, activateVersion } = useCguAdmin()
onMounted(fetchVersions)

// null = viewing/editing the active version (the only editable state) - same convention as
// PromptEditor.vue, just a single global sequence here instead of one per prompt name.
const selectedVersion = ref<number | null>(null)
const draft = ref('')
const publishing = ref(false)
const published = ref(false)
const rollingBack = ref(false)

const currentActive = computed(() => versions.value.find((v) => v.is_active))
const viewedVersion = computed(() =>
  selectedVersion.value === null ? null : versions.value.find((v) => v.version === selectedVersion.value),
)
const isViewingPast = computed(() => selectedVersion.value !== null)

watch(
  currentActive,
  (value) => {
    if (value && selectedVersion.value === null) draft.value = value.content
  },
  { immediate: true },
)

function selectVersion(version: number | null) {
  selectedVersion.value = version
  draft.value = version === null ? (currentActive.value?.content ?? '') : (viewedVersion.value?.content ?? '')
}

async function publish() {
  if (!draft.value.trim()) return
  publishing.value = true
  const created = await createVersion(draft.value)
  if (created) {
    const latest = versions.value[0]
    if (latest) await activateVersion(latest.version)
    published.value = true
    setTimeout(() => (published.value = false), 2000)
  }
  publishing.value = false
}

async function rollback() {
  if (selectedVersion.value === null) return
  rollingBack.value = true
  await activateVersion(selectedVersion.value)
  selectVersion(null)
  rollingBack.value = false
}

const dateFormatter = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
function formatDate(iso: string) {
  return dateFormatter.format(new Date(iso))
}
</script>

<template>
  <div class="cgu-editor">
    <div class="cgu-editor__header">
      <span v-if="currentActive" class="cgu-editor__badge">v{{ currentActive.version }} active</span>
      <span v-else class="cgu-editor__badge cgu-editor__badge--none">Aucune version active</span>

      <label class="cgu-editor__version-picker">
        <span class="cgu-editor__version-picker-label">Version</span>
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

    <p class="cgu-editor__hint">
      Publier une nouvelle version force chaque utilisateur ayant déjà accepté une version précédente à
      accepter celle-ci avant de pouvoir continuer à utiliser l'app - l'ancienne reste consultable dans
      l'historique, jamais écrasée.
    </p>

    <p v-if="isViewingPast" class="cgu-editor__readonly-hint">
      Version passée en lecture seule (v{{ selectedVersion }}, {{ formatDate(viewedVersion?.created_at ?? '') }}) -
      revenez à la version actuelle pour éditer, ou activez celle-ci pour en faire la nouvelle version courante.
    </p>

    <textarea
      v-model="draft"
      class="cgu-editor__textarea fr-input"
      :class="{ 'cgu-editor__textarea--readonly': isViewingPast }"
      aria-label="Contenu des CGU (markdown)"
      :readonly="isViewingPast"
      rows="14"
    />

    <div class="cgu-editor__footer">
      <span v-if="published" class="cgu-editor__saved">Publié</span>
      <button
        v-if="isViewingPast"
        type="button"
        class="fr-btn fr-btn--sm"
        :disabled="rollingBack"
        @click="rollback"
      >
        {{ rollingBack ? 'Activation…' : 'Revenir à cette version' }}
      </button>
      <button v-else type="button" class="fr-btn fr-btn--sm" :disabled="!draft.trim() || publishing" @click="publish">
        {{ publishing ? 'Publication…' : 'Publier cette version' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.cgu-editor {
  padding: 1.25rem;
}

.cgu-editor__header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.625rem;
  margin-bottom: 0.75rem;
}

.cgu-editor__badge {
  font-size: 0.6875rem;
  font-weight: 600;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  background: var(--background-success-default);
  color: var(--text-inverted-default);
}

.cgu-editor__badge--none {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
}

.cgu-editor__version-picker {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.cgu-editor__version-picker select {
  font-size: 0.8125rem;
  padding: 0.25rem 0.5rem;
}

.cgu-editor__hint {
  margin: 0 0 0.625rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.cgu-editor__readonly-hint {
  margin: 0 0 0.625rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
  font-size: 0.8125rem;
}

.cgu-editor__textarea {
  width: 100%;
  box-sizing: border-box;
  font-family: 'Consolas', monospace;
  font-size: 0.8125rem;
  resize: vertical;
}

.cgu-editor__textarea--readonly {
  background: var(--background-alt-grey);
  color: var(--text-mention-grey);
  cursor: default;
}

.cgu-editor__footer {
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.cgu-editor__saved {
  font-size: 0.875rem;
  color: var(--text-default-success);
}
</style>
