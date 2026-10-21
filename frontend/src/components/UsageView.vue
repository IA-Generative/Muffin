<script setup lang="ts">
import { ref } from 'vue'
import { useUsage } from '../composables/useUsage'
import UsageCharts from './usage/UsageCharts.vue'
import UsagePeriodSelector from './usage/UsagePeriodSelector.vue'

const days = ref(30)
const { usage, isLoading, error } = useUsage(days)
</script>

<template>
  <section class="usage-view">
    <div class="usage-view__header">
      <h1>Ma consommation</h1>
      <UsagePeriodSelector v-model="days" />
    </div>
    <p class="usage-view__intro">
      Les tokens consommés par vos questions dans le chat et par le traitement des documents que vous ajoutez (résumé,
      questions-réponses, découpage, extraction, tags…).
    </p>

    <div class="usage-view__content">
      <p v-if="error" class="usage-view__error" role="alert">{{ error }}</p>
      <p v-else-if="isLoading && !usage" class="usage-view__empty">Chargement…</p>
      <p v-else-if="usage && usage.totals.calls === 0" class="usage-view__empty">
        Aucune consommation sur les {{ days }} derniers jours.
      </p>
      <UsageCharts v-else-if="usage" :usage="usage" />
    </div>
  </section>
</template>

<style scoped>
.usage-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.usage-view__header,
.usage-view__intro,
.usage-view__content {
  max-width: 64rem;
  margin: 0 auto;
}

.usage-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.usage-view__header h1 {
  margin: 0;
}

.usage-view__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.usage-view__empty,
.usage-view__error {
  margin: 3rem 0;
  text-align: center;
  color: var(--text-mention-grey);
}

.usage-view__error {
  color: var(--text-default-error);
}
</style>
