<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TabularProfile } from '../types/tabular'
import {
  cellText,
  columnDetails,
  formatCount,
  formatDistinct,
  isLegacyProfile,
  sheetNotes,
  sheetsOf,
  typeLabel,
} from '../utils/tabular'

const props = defineProps<{ profile: TabularProfile }>()

const sheets = computed(() => sheetsOf(props.profile))
const selected = ref(0)
watch(sheets, () => (selected.value = 0))

const sheet = computed(() => sheets.value[selected.value] ?? sheets.value[0])
const notes = computed(() => (sheet.value ? sheetNotes(sheet.value) : []))
const sqlTypes = computed(
  () => new Map((sheet.value?.table?.columns ?? []).map((column) => [column.name, column.sql_type])),
)
</script>

<template>
  <div class="tabular">
    <p v-if="isLegacyProfile(profile)" class="tabular__legacy">
      <span class="fr-badge fr-badge--sm fr-badge--info fr-badge--no-icon">Profil ancien</span>
      Seule la feuille principale est décrite. Réindexez le document pour voir toutes les feuilles du fichier.
    </p>

    <div v-if="sheets.length > 1" class="tabular__sheets" role="tablist" aria-label="Feuilles du fichier">
      <button
        v-for="(item, position) in sheets"
        :key="item.index"
        type="button"
        role="tab"
        class="tabular__sheet"
        :class="{ 'tabular__sheet--active': position === selected }"
        :aria-selected="position === selected"
        @click="selected = position"
      >
        {{ item.name }}
      </button>
    </div>

    <template v-if="sheet">
      <p class="tabular__summary">
        <strong>{{ formatCount(sheet.rows) }}</strong> ligne(s) · <strong>{{ sheet.columns.length }}</strong> colonne(s)
        <span v-if="sheet.hidden" class="fr-badge fr-badge--sm fr-badge--no-icon">masquée</span>
        <span v-if="sheet.truncated" class="fr-badge fr-badge--sm fr-badge--warning fr-badge--no-icon">tronquée</span>
        <span v-if="sheet.header_detected" class="fr-badge fr-badge--sm fr-badge--no-icon">en-tête reconnu</span>
      </p>

      <ul v-if="notes.length" class="tabular__notes">
        <li v-for="note in notes" :key="note">{{ note }}</li>
      </ul>

      <p v-if="!sheet.columns.length" class="tabular__empty">Cette feuille ne contient pas de données.</p>
      <template v-else>
        <h3 class="tabular__title">Colonnes</h3>
        <div class="tabular__scroll">
          <table class="tabular__table">
            <thead>
              <tr>
                <th scope="col">Nom</th>
                <th scope="col">Type</th>
                <th scope="col">Renseignées</th>
                <th scope="col">Vides</th>
                <th scope="col">Distinctes</th>
                <th scope="col">Détail</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="column in sheet.columns" :key="column.index">
                <th scope="row">{{ column.name }}</th>
                <td>
                  {{ typeLabel(column.type) }}
                  <small v-if="sqlTypes.get(column.name)" class="tabular__sql">{{ sqlTypes.get(column.name) }}</small>
                </td>
                <td>{{ formatCount(column.non_null) }}</td>
                <td>{{ formatCount(column.null) }}</td>
                <td>{{ formatDistinct(column) }}</td>
                <td>
                  <span v-for="detail in columnDetails(column)" :key="detail" class="tabular__detail">{{ detail }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <template v-if="sheet.preview.length">
          <h3 class="tabular__title">Aperçu</h3>
          <div class="tabular__scroll">
            <table class="tabular__table">
              <thead>
                <tr>
                  <th v-for="column in sheet.columns" :key="column.index" scope="col">{{ column.name }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, rowIndex) in sheet.preview" :key="rowIndex">
                  <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cellText(cell) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </template>
  </div>
</template>

<style scoped>
.tabular__legacy,
.tabular__summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 0.75rem;
  font-size: 0.875rem;
}

.tabular__sheets {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.75rem;
}

.tabular__sheet {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: transparent;
  color: inherit;
  padding: 0.25rem 0.625rem;
  font-size: 0.8125rem;
  cursor: pointer;
}

.tabular__sheet--active {
  background: var(--background-action-low-blue-france);
  border-color: var(--border-active-blue-france);
  color: var(--text-action-high-blue-france);
}

.tabular__notes {
  margin: 0 0 0.75rem;
  padding-left: 1.25rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.tabular__title {
  margin: 1rem 0 0.5rem;
  font-size: 0.9375rem;
}

.tabular__empty {
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.tabular__scroll {
  overflow-x: auto;
}

.tabular__table {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.8125rem;
}

.tabular__table th,
.tabular__table td {
  border-bottom: 1px solid var(--border-default-grey);
  padding: 0.3rem 0.5rem;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}

.tabular__table thead th {
  color: var(--text-mention-grey);
  font-weight: 500;
}

.tabular__sql {
  display: block;
  color: var(--text-mention-grey);
}

.tabular__detail {
  display: block;
  color: var(--text-mention-grey);
}
</style>
