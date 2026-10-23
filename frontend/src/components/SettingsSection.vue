<script setup lang="ts">
// Une section repliable des paramètres : un titre, ce qui est réglé aujourd'hui en une ligne (visible même repliée,
// pour lire l'ensemble d'un coup d'œil), un repère « Modifié » / « À corriger », puis le contenu. Les réglages
// techniques vont dans le slot « advanced », replié par défaut.
import { computed, ref, useId, watch } from 'vue'
import '../assets/settings-form.css'

const props = defineProps<{
  title: string
  summary: string
  changed?: boolean
  invalid?: boolean
  // Ouverte d'office (ex. un champ à corriger).
  forceOpen?: boolean
}>()

const open = ref(false)
const advancedOpen = ref(false)
const uid = useId()
const panelId = computed(() => `${uid}-panel`)
const advancedId = computed(() => `${uid}-advanced`)

watch(
  () => props.forceOpen,
  (value) => {
    if (value) open.value = true
  },
  { immediate: true },
)
</script>

<template>
  <section class="settings-section" :class="{ 'settings-section--open': open }">
    <h4 class="settings-section__heading">
      <button
        type="button"
        class="settings-section__toggle"
        :aria-expanded="open"
        :aria-controls="panelId"
        @click="open = !open"
      >
        <span class="settings-section__text">
          <span class="settings-section__title">{{ title }}</span>
          <span class="settings-section__summary">{{ summary }}</span>
        </span>
        <span v-if="invalid" class="sf-badge sf-badge--error">À corriger</span>
        <span v-else-if="changed" class="sf-badge sf-badge--changed">Modifié</span>
        <span class="settings-section__chevron" aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      </button>
    </h4>
    <div v-show="open" :id="panelId" class="settings-section__body">
      <slot />
      <template v-if="$slots.advanced">
        <button
          type="button"
          class="settings-section__advanced-toggle"
          :aria-expanded="advancedOpen"
          :aria-controls="advancedId"
          @click="advancedOpen = !advancedOpen"
        >
          {{ advancedOpen ? '▾' : '▸' }} Réglages avancés
        </button>
        <div v-show="advancedOpen" :id="advancedId" class="settings-section__advanced">
          <slot name="advanced" />
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.settings-section {
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.settings-section--open {
  border-color: var(--border-active-blue-france);
}

.settings-section__heading {
  margin: 0;
}

.settings-section__toggle {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.875rem 1rem;
  border: 0;
  border-radius: 0.75rem;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.settings-section__text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.settings-section__title {
  font-size: 0.9375rem;
  font-weight: 700;
}

.settings-section__summary {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.settings-section__chevron {
  flex-shrink: 0;
  color: var(--text-action-high-blue-france);
}

.settings-section__body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 0.25rem 1rem 1rem;
}

.settings-section__advanced-toggle {
  align-self: flex-start;
  padding: 0.25rem 0;
  border: 0;
  background: none;
  color: var(--text-action-high-blue-france);
  font: inherit;
  font-size: 0.8125rem;
  font-weight: 700;
  cursor: pointer;
}

.settings-section__advanced {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 0.75rem 0.875rem;
  border-left: 3px solid var(--border-default-grey);
  background: var(--background-alt-grey);
  border-radius: 0 0.5rem 0.5rem 0;
}
</style>
