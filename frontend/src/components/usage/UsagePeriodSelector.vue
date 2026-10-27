<script setup lang="ts">
// 365 days is the longest period the API gives.
const PERIODS = [7, 30, 90, 365] as const;

const days = defineModel<number>({ required: true });
</script>

<template>
  <div class="period" role="group" aria-label="Période">
    <button
      v-for="period in PERIODS"
      :key="period"
      type="button"
      class="fr-btn fr-btn--sm"
      :class="{ 'fr-btn--secondary': days !== period }"
      :aria-pressed="days === period"
      @click="days = period"
    >
      {{ period === 365 ? "1 an" : `${period} jours` }}
    </button>
  </div>
</template>

<style scoped>
.period {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}
</style>
