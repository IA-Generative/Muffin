<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useCollections } from '../composables/useCollections'
import { METRICS, METRIC_FAMILIES, MOCK_EVALUATION_RUNS, seedFromId, type MetricFamily } from '../data/qualityMetrics'

// Not connected to the backend yet (see #33 and data/qualityMetrics.ts) - every number here is a
// deterministic mock seeded from the selected collection, standing in for what #11/#30/#31/#32
// will eventually provide for real. Nothing here recomputes a metric, this view only aggregates
// and displays (per #33's own scope).
const { collections } = useCollections()

const selectedCollectionId = ref<'all' | string>('all')
const seed = computed(() =>
  selectedCollectionId.value === 'all' ? seedFromId('__all__') : seedFromId(selectedCollectionId.value),
)

// Only retrieval has a real notion of a versioned "evaluation run" (see #11's EvaluationRun) -
// meaningless for "toutes les collections" (an eval run belongs to exactly one collection), so
// this resets to the most recent run whenever the collection scope changes away from a single one.
const selectedEvalRunIndex = ref(0)
watch(selectedCollectionId, () => {
  selectedEvalRunIndex.value = 0
})
const retrievalSeed = computed(() => seed.value + (selectedEvalRunIndex.value + 1) * 10_000)

function seedFor(family: MetricFamily): number {
  return family === 'retrieval' ? retrievalSeed.value : seed.value
}

function metricsFor(family: MetricFamily) {
  return METRICS.filter((metric) => metric.family === family)
}
</script>

<template>
  <section class="quality-view">
    <div class="quality-view__header">
      <h1>Qualité</h1>
      <p class="quality-view__intro">
        Vue d'ensemble des métriques de qualité de l'agent - retrieval, retours utilisateur, cohérence de
        discussion, groundedness, et coût/latence. Ces chiffres sont des exemples le temps que chaque famille
        soit branchée sur de vraies données (voir les issues citées sous chaque section). Le "n =" sous chaque
        chiffre indique sur combien de points de mesure il est calculé - un pourcentage sur 5 mesures ne se lit
        pas comme un pourcentage sur 500.
      </p>

      <div class="quality-view__scope">
        <div class="quality-view__scope-field">
          <label for="quality-collection-picker">Collection</label>
          <select id="quality-collection-picker" v-model="selectedCollectionId" class="fr-select">
            <option value="all">Toutes les collections</option>
            <option v-for="collection in collections" :key="collection.id" :value="collection.id">
              {{ collection.name }}
            </option>
          </select>
        </div>

        <div v-if="selectedCollectionId !== 'all'" class="quality-view__scope-field">
          <label for="quality-eval-run-picker">Run d'évaluation (retrieval)</label>
          <select id="quality-eval-run-picker" v-model.number="selectedEvalRunIndex" class="fr-select">
            <option v-for="(run, index) in MOCK_EVALUATION_RUNS" :key="run.id" :value="index">
              {{ run.label }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <section v-for="family in METRIC_FAMILIES" :key="family.id" class="quality-family">
      <div class="quality-family__header">
        <h2>{{ family.label }}</h2>
        <span v-if="family.issue" class="quality-family__issue">{{ family.issue }}</span>
      </div>
      <p class="quality-family__description">{{ family.description }}</p>

      <div class="quality-family__grid">
        <article v-for="metric in metricsFor(family.id)" :key="metric.id" class="quality-metric">
          <p class="quality-metric__value">{{ metric.format(metric.mockValue(seedFor(family.id))) }}</p>
          <p class="quality-metric__label">{{ metric.label }}</p>
          <p class="quality-metric__sample">n = {{ metric.mockSampleSize(seedFor(family.id)) }}</p>
          <p class="quality-metric__description">{{ metric.description }}</p>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.quality-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem 3rem;
  box-sizing: border-box;
}

.quality-view__header {
  max-width: 64rem;
  margin: 0 auto 2rem;
}

.quality-view__header h1 {
  margin: 0;
}

.quality-view__intro {
  margin: 0.5rem 0 1.25rem;
  color: var(--text-mention-grey);
  max-width: 42rem;
}

.quality-view__scope {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 1.25rem;
}

.quality-view__scope-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.quality-view__scope-field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.quality-view__scope-field select {
  max-width: 20rem;
}

.quality-family {
  max-width: 64rem;
  margin: 0 auto 2.5rem;
}

.quality-family__header {
  display: flex;
  align-items: baseline;
  gap: 0.625rem;
}

.quality-family__header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.quality-family__issue {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.quality-family__description {
  margin: 0.375rem 0 1rem;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
  max-width: 42rem;
}

.quality-family__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 1rem;
}

.quality-metric {
  padding: 1.125rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.quality-metric__value {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
}

.quality-metric__label {
  margin: 0.25rem 0 0.125rem;
  font-weight: 700;
  font-size: 0.875rem;
}

.quality-metric__sample {
  margin: 0 0 0.5rem;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.quality-metric__description {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}
</style>
