<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import {
  AA_BATTERY_WH,
  LED_BULB_WATTS,
  batteryCount,
  bulbSeconds,
  formatDuration,
  formatEnergy,
} from "../../utils/execution";

const props = defineProps<{
  energyWh: number;
  period: string;
}>();

const MAX_BATTERIES = 10;

// Inside the battery (viewBox 0 0 30 80): the charge goes from the bottom of the body to its top.
const BODY = { x: 3, y: 8, width: 24, height: 68, radius: 4 };

const clipId = useId();
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)",
).matches;

const count = computed(() => batteryCount(props.energyWh));
const total = computed(() => Math.max(1, Math.ceil(count.value)));
const levels = computed(() =>
  Array.from({ length: Math.min(total.value, MAX_BATTERIES) }, (_, index) =>
    Math.min(1, Math.max(0, count.value - index)),
  ),
);
const hidden = computed(() => total.value - levels.value.length);

// The figure counts up and the batteries charge from empty, replayed whenever the energy changes.
const shownSeconds = ref(0);
const charged = ref(false);
let frame = 0;

function animate() {
  cancelAnimationFrame(frame);
  charged.value = false;
  const target = bulbSeconds(props.energyWh);
  if (reducedMotion) {
    shownSeconds.value = target;
    charged.value = true;
    return;
  }
  const start = performance.now();
  frame = requestAnimationFrame(function tick(now) {
    charged.value = true;
    const progress = Math.min(1, (now - start) / 1600);
    shownSeconds.value = target * (1 - (1 - progress) ** 3);
    if (progress < 1) frame = requestAnimationFrame(tick);
  });
}

onMounted(animate);
watch(() => props.energyWh, animate);
onBeforeUnmount(() => cancelAnimationFrame(frame));

function chargeOffset(level: number) {
  return charged.value ? BODY.height * (1 - level) : BODY.height;
}

const batteriesLabel = computed(() => {
  const value = count.value;
  if (value < 1)
    return `${(value * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} % d’une pile AA`;
  const full = Math.floor(value);
  return `soit ${value.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} pile${value >= 2 ? "s" : ""} AA (${full.toLocaleString("fr-FR")} pleine${full >= 2 ? "s" : ""})`;
});
</script>

<template>
  <section class="energy">
    <h2 class="energy__title">Énergie consommée · {{ period }}</h2>
    <div class="energy__body">
      <div class="energy__figure">
        <span class="energy__bulb-line">
          <svg viewBox="0 0 24 32" class="energy__bulb" aria-hidden="true">
            <path
              d="M12 2a8 8 0 0 0-4.5 14.6c.9.7 1.5 1.7 1.5 2.9V21h6v-1.5c0-1.2.6-2.2 1.5-2.9A8 8 0 0 0 12 2Z"
              class="energy__bulb-glass"
            />
            <path d="M9 24h6M10 27.5h4" class="energy__bulb-base" />
          </svg>
          <span
            class="energy__time"
            :aria-label="formatDuration(bulbSeconds(energyWh))"
          >
            {{ formatDuration(shownSeconds) }}
          </span>
        </span>
        <span class="energy__caption"
          >d’une ampoule LED de {{ LED_BULB_WATTS }} W allumée</span
        >
        <span class="energy__caption">{{ batteriesLabel }}</span>
      </div>
      <div
        class="energy__batteries"
        role="img"
        :aria-label="`${formatEnergy(energyWh)}, soit ${count.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} pile AA`"
      >
        <svg
          v-for="(level, index) in levels"
          :key="index"
          viewBox="0 0 30 80"
          class="energy__battery"
          aria-hidden="true"
        >
          <defs>
            <clipPath :id="`${clipId}-${index}`">
              <rect
                :x="BODY.x"
                :y="BODY.y"
                :width="BODY.width"
                :height="BODY.height"
                :rx="BODY.radius"
              />
            </clipPath>
          </defs>
          <g :clip-path="`url(#${clipId}-${index})`">
            <rect
              :x="BODY.x"
              :y="BODY.y"
              :width="BODY.width"
              :height="BODY.height"
              class="energy__charge"
              :style="{
                transform: `translateY(${chargeOffset(level)}px)`,
                transitionDelay: `${index * 140}ms`,
              }"
            />
          </g>
          <rect
            :x="BODY.x"
            :y="BODY.y"
            :width="BODY.width"
            :height="BODY.height"
            :rx="BODY.radius"
            class="energy__outline"
          />
          <rect
            x="10"
            y="2"
            width="10"
            height="6"
            rx="1.5"
            class="energy__terminal"
          />
        </svg>
        <span v-if="hidden > 0" class="energy__more"
          >+ {{ hidden.toLocaleString("fr-FR") }}</span
        >
      </div>
    </div>
    <p class="energy__note">
      Pour se représenter {{ formatEnergy(energyWh) }} (estimation, voir plus
      bas) : une ampoule LED de {{ LED_BULB_WATTS }} W, ou une pile alcaline AA
      de {{ AA_BATTERY_WH.toLocaleString("fr-FR") }} Wh. Des ordres de grandeur,
      pas des mesures.
    </p>
  </section>
</template>

<style scoped>
.energy {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
}

.energy__title {
  margin: 0;
  font-size: 1rem;
}

.energy__body {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.75rem 1.5rem;
}

.energy__figure {
  display: flex;
  flex-direction: column;
}

.energy__bulb-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.energy__bulb {
  width: 1.5rem;
  height: 2rem;
}

.energy__bulb-glass {
  fill: var(--background-action-high-blue-france);
  opacity: 0.8;
}

.energy__bulb-base {
  fill: none;
  stroke: var(--text-mention-grey);
  stroke-width: 1.5;
  stroke-linecap: round;
}

.energy__time {
  font-size: 1.875rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.energy__caption,
.energy__note,
.energy__more {
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.energy__note {
  margin: 0;
}

.energy__batteries {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.375rem;
}

.energy__battery {
  flex-shrink: 0;
  width: 1.875rem;
  height: 5rem;
}

.energy__charge {
  fill: var(--background-action-high-blue-france);
  opacity: 0.8;
  transition: transform 1600ms cubic-bezier(0.22, 1, 0.36, 1);
}

.energy__outline {
  fill: none;
  stroke: var(--text-mention-grey);
  stroke-width: 1.5;
}

.energy__terminal {
  fill: var(--text-mention-grey);
}

@media (prefers-reduced-motion: reduce) {
  .energy__charge {
    transition: none;
  }
}
</style>
