<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

const props = defineProps<{
  totalTokens: number;
  period: string;
}>();

// There is no published per-token figure. This one comes from Google's 0.26 mL for a median
// Gemini prompt (a few hundred tokens), which counts the cooling on site only: an estimate on the
// low side (taking the power generation into account gives 10x more or higher).
const ML_PER_1K_TOKENS = 0.5;
const MAX_BOTTLES = 10;

// Inside the bottle (viewBox 0 0 40 100): the water goes from the bottom to just under the neck.
const WATER_BOTTOM = 96;
const WATER_TOP = 14;
const WATER_RANGE = WATER_BOTTOM - WATER_TOP;
const BOTTLE =
  "M15 2 h10 v10 c0 6 9 10 9 22 v58 a6 6 0 0 1 -6 6 h-16 a6 6 0 0 1 -6 -6 v-58 c0 -12 9 -16 9 -22 z";
// Two wave lengths of 40, so sliding it by one wave length loops seamlessly.
const WAVE = "M0 3 q10 -5 20 0 t20 0 t20 0 t20 0 V12 H0 z";

const clipId = useId();
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)",
).matches;

const liters = computed(
  () => (props.totalTokens * ML_PER_1K_TOKENS) / 1000 / 1000,
);
const bottleCount = computed(() => Math.max(1, Math.ceil(liters.value)));
const levels = computed(() =>
  Array.from({ length: Math.min(bottleCount.value, MAX_BOTTLES) }, (_, index) =>
    Math.min(1, Math.max(0, liters.value - index)),
  ),
);
const hiddenBottles = computed(() => bottleCount.value - levels.value.length);

// The figure counts up and the bottles fill from empty, replayed whenever the figure changes.
const shownLiters = ref(0);
const filled = ref(false);
let frame = 0;

function animate() {
  cancelAnimationFrame(frame);
  filled.value = false;
  if (reducedMotion) {
    shownLiters.value = liters.value;
    filled.value = true;
    return;
  }
  const target = liters.value;
  const start = performance.now();
  frame = requestAnimationFrame(function tick(now) {
    filled.value = true;
    const progress = Math.min(1, (now - start) / 1600);
    shownLiters.value = target * (1 - (1 - progress) ** 3);
    if (progress < 1) frame = requestAnimationFrame(tick);
  });
}

onMounted(animate);
watch(liters, animate);
onBeforeUnmount(() => cancelAnimationFrame(frame));

function waterOffset(level: number) {
  return filled.value ? WATER_RANGE * (1 - level) : WATER_RANGE + 8;
}

function formatLiters(value: number) {
  return value >= 1
    ? `${value.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} L`
    : `${(value * 1000).toLocaleString("fr-FR", { maximumFractionDigits: value * 1000 < 10 ? 2 : 0 })} mL`;
}

const bottlesLabel = computed(() => {
  const value = liters.value;
  if (value < 1)
    return `${(value * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} % d’une bouteille de 1 L`;
  const full = Math.floor(value);
  return `soit ${full.toLocaleString("fr-FR")} bouteille${full >= 2 ? "s" : ""} de 1 L pleine${full >= 2 ? "s" : ""}`;
});
</script>

<template>
  <section class="water">
    <h2 class="water__title">Eau consommée · {{ period }}</h2>
    <div class="water__body">
      <div class="water__figure">
        <span class="water__liters" :aria-label="formatLiters(liters)">{{
          formatLiters(shownLiters)
        }}</span>
        <span class="water__caption">{{ bottlesLabel }}</span>
      </div>
      <div
        class="water__bottles"
        role="img"
        :aria-label="`${formatLiters(liters)} d’eau en bouteilles de 1 L`"
      >
        <svg
          v-for="(level, index) in levels"
          :key="index"
          viewBox="0 0 40 100"
          class="water__bottle"
          aria-hidden="true"
        >
          <defs>
            <clipPath :id="`${clipId}-${index}`">
              <path :d="BOTTLE" />
            </clipPath>
          </defs>
          <g :clip-path="`url(#${clipId}-${index})`">
            <g
              class="water__level"
              :style="{
                transform: `translateY(${waterOffset(level)}px)`,
                transitionDelay: `${index * 140}ms`,
              }"
            >
              <g :transform="`translate(0 ${WATER_TOP - 3})`">
                <path :d="WAVE" class="water__wave" />
                <rect
                  x="0"
                  y="11"
                  width="40"
                  height="100"
                  class="water__fill"
                />
              </g>
            </g>
          </g>
          <path :d="BOTTLE" class="water__outline" />
          <rect x="14" y="0" width="12" height="3" rx="1" class="water__cap" />
        </svg>
        <span v-if="hiddenBottles > 0" class="water__more"
          >+ {{ hiddenBottles.toLocaleString("fr-FR") }}</span
        >
      </div>
    </div>
    <p class="water__note">
      Estimation : {{ ML_PER_1K_TOKENS.toLocaleString("fr-FR") }} mL d’eau pour
      1 000 tokens (refroidissement des data centers uniquement, sans la
      production d’électricité). Un ordre de grandeur, pas une mesure.
    </p>
  </section>
</template>

<style scoped>
.water {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.water__title {
  margin: 0;
  font-size: 1rem;
}

.water__body {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.75rem 1.5rem;
}

.water__figure {
  display: flex;
  flex-direction: column;
}

.water__liters {
  font-size: 1.875rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.water__caption,
.water__note,
.water__more {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.water__note {
  margin: 0;
}

.water__bottles {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.375rem;
}

.water__bottle {
  flex-shrink: 0;
  width: 2.5rem;
  height: 6rem;
}

.water__level {
  transition: transform 1600ms cubic-bezier(0.22, 1, 0.36, 1);
}

.water__wave,
.water__fill {
  fill: var(--background-action-high-blue-france);
  opacity: 0.8;
}

.water__wave {
  animation: water-wave 2.4s linear infinite;
}

.water__outline {
  fill: none;
  stroke: var(--text-mention-grey);
  stroke-width: 1.5;
}

.water__cap {
  fill: var(--text-mention-grey);
}

@keyframes water-wave {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-40px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .water__level {
    transition: none;
  }

  .water__wave {
    animation: none;
  }
}
</style>
