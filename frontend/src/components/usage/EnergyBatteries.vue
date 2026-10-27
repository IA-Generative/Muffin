<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import {
  LED_BULB_WATTS,
  PHONE_BATTERY_WH,
  bulbSeconds,
  formatDuration,
  foldFull,
  formatEnergy,
  phoneCharges,
} from '../../utils/execution'

const props = defineProps<{
  energyWh: number
  period: string
}>()

const MAX_BATTERIES = 6

// Inside a battery (viewBox 0 0 60 28): the charge fills the track from the left.
const TRACK = { x: 3.5, y: 3.5, width: 45, height: 21, radius: 5.5 }
const SHINE_WIDTH = 16

const clipId = useId()
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

const charges = computed(() => phoneCharges(props.energyWh))
const total = computed(() => Math.max(1, Math.ceil(charges.value)))
const fold = computed(() => foldFull(total.value, MAX_BATTERIES))

// The figures count up and the batteries charge one after the other, replayed whenever the energy changes.
const progress = ref(0)
let frame = 0

function animate() {
  cancelAnimationFrame(frame)
  if (reducedMotion) {
    progress.value = 1
    return
  }
  progress.value = 0
  const start = performance.now()
  frame = requestAnimationFrame(function tick(now) {
    const elapsed = Math.min(1, (now - start) / 2000)
    progress.value = 1 - (1 - elapsed) ** 3
    if (elapsed < 1) frame = requestAnimationFrame(tick)
  })
}

onMounted(animate)
watch(() => props.energyWh, animate)
onBeforeUnmount(() => cancelAnimationFrame(frame))

const shownSeconds = computed(() => bulbSeconds(props.energyWh) * progress.value)
// The batteries drawn are the last ones, so the one still filling is always seen; the full ones before them
// are a count, that grows as the charge goes by.
const levels = computed(() =>
  Array.from({ length: fold.value.shown }, (_, index) =>
    Math.min(1, Math.max(0, charges.value * progress.value - (fold.value.folded + index))),
  ),
)
const foldedFull = computed(() => Math.min(fold.value.folded, Math.floor(charges.value * progress.value)))
const percent = (level: number) => `${Math.round(level * 100)} %`

const chargesLabel = computed(() => {
  const value = charges.value
  if (value < 1)
    return `${(value * 100).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} % d’une batterie de smartphone`
  return `soit ${value.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} charges de smartphone`
})
</script>

<template>
  <section class="energy">
    <h2 class="energy__title">Énergie consommée · {{ period }}</h2>
    <div class="energy__body">
      <div class="energy__figure">
        <span class="energy__bulb-line">
          <svg viewBox="-4 -5 32 39" class="energy__bulb" aria-hidden="true">
            <g class="energy__rays">
              <path d="M12 -3.5V-0.5M3 -0.5L1 -2.5M21 -0.5L23 -2.5M0.5 9H-2.5M23.5 9H26.5" />
            </g>
            <path
              d="M12 2a8 8 0 0 0-4.5 14.6c.9.7 1.5 1.7 1.5 2.9V21h6v-1.5c0-1.2.6-2.2 1.5-2.9A8 8 0 0 0 12 2Z"
              class="energy__bulb-glass"
            />
            <path d="M9 24h6M10 27.5h4" class="energy__bulb-base" />
          </svg>
          <span class="energy__time" :aria-label="formatDuration(bulbSeconds(energyWh))">
            {{ formatDuration(shownSeconds) }}
          </span>
        </span>
        <span class="energy__caption">d’une ampoule LED de {{ LED_BULB_WATTS }} W allumée</span>
        <span class="energy__caption">{{ chargesLabel }}</span>
      </div>
      <div
        class="energy__batteries"
        role="img"
        :aria-label="`${formatEnergy(energyWh)}, soit ${charges.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} charge de smartphone`"
      >
        <span v-if="fold.folded > 0" class="energy__more">
          {{ foldedFull.toLocaleString('fr-FR') }} batteries pleines
        </span>
        <div v-for="(level, index) in levels" :key="index" class="energy__phone">
          <svg viewBox="0 0 60 28" class="energy__battery" aria-hidden="true">
            <defs>
              <clipPath :id="`${clipId}-${index}`">
                <rect :x="TRACK.x" :y="TRACK.y" :width="TRACK.width" :height="TRACK.height" :rx="TRACK.radius" />
              </clipPath>
              <linearGradient :id="`${clipId}-shine`" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stop-color="#fff" stop-opacity="0" />
                <stop offset="0.5" stop-color="#fff" stop-opacity="0.55" />
                <stop offset="1" stop-color="#fff" stop-opacity="0" />
              </linearGradient>
            </defs>
            <rect x="1" y="1" width="50" height="26" rx="8" class="energy__outline" />
            <rect x="53.5" y="9.5" width="4" height="9" rx="2" class="energy__nub" />
            <rect
              :x="TRACK.x"
              :y="TRACK.y"
              :width="TRACK.width"
              :height="TRACK.height"
              :rx="TRACK.radius"
              class="energy__track"
            />
            <g :clip-path="`url(#${clipId}-${index})`">
              <rect
                :x="TRACK.x"
                :y="TRACK.y"
                :width="TRACK.width * level"
                :height="TRACK.height"
                class="energy__charge"
              />
              <svg
                :x="TRACK.x"
                :y="TRACK.y"
                :width="TRACK.width * level"
                :height="TRACK.height"
                class="energy__shine-clip"
              >
                <rect
                  x="0"
                  y="0"
                  :width="SHINE_WIDTH"
                  :height="TRACK.height"
                  :fill="`url(#${clipId}-shine)`"
                  class="energy__shine"
                  :style="{ animationDelay: `${index * 250}ms` }"
                />
              </svg>
            </g>
            <path v-if="level > 0 && level < 1" d="M31 5 24 15.5h4.5L27 23l7-10.5h-4.5z" class="energy__bolt" />
          </svg>
          <span class="energy__percent">{{ percent(level) }}</span>
        </div>
      </div>
    </div>
    <p class="energy__note">
      Pour se représenter {{ formatEnergy(energyWh) }} (une estimation) : une ampoule LED de {{ LED_BULB_WATTS }} W, ou
      la batterie d’un smartphone de {{ PHONE_BATTERY_WH.toLocaleString('fr-FR') }} Wh. Des ordres de grandeur, pas des
      mesures.
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
  width: 2rem;
  height: 2.4rem;
  overflow: visible;
}

.energy__bulb-glass {
  fill: #fcc63a;
  filter: drop-shadow(0 0 6px rgb(252 198 58 / 0.85));
  animation: energy-flicker 3.2s linear infinite;
}

.energy__rays {
  fill: none;
  stroke: #fcc63a;
  stroke-width: 1.5;
  stroke-linecap: round;
  animation: energy-flicker 3.2s linear infinite;
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
  align-items: center;
  gap: 0.5rem 1rem;
}

.energy__phone {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.energy__battery {
  flex-shrink: 0;
  width: 4.5rem;
  height: 2.1rem;
}

.energy__percent {
  min-width: 3rem;
  font-size: 0.875rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.energy__outline {
  fill: none;
  stroke: var(--text-mention-grey);
  stroke-opacity: 0.55;
  stroke-width: 1.5;
}

.energy__nub {
  fill: var(--text-mention-grey);
  fill-opacity: 0.55;
}

.energy__track {
  fill: var(--text-mention-grey);
  fill-opacity: 0.18;
}

.energy__charge {
  fill: #34c759;
}

.energy__shine-clip {
  overflow: hidden;
}

/* The light sweeping along the charge, as on a phone that is plugged in. */
.energy__shine {
  animation: energy-sweep 1.9s ease-in-out infinite;
}

.energy__bolt {
  fill: #fff;
  stroke: rgb(0 0 0 / 0.35);
  stroke-width: 0.8;
  stroke-linejoin: round;
  animation: energy-pulse 1.6s ease-in-out infinite;
}

@keyframes energy-sweep {
  from {
    transform: translateX(-16px);
  }

  to {
    transform: translateX(46px);
  }
}

@keyframes energy-pulse {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.55;
  }
}

/* A bulb that is not quite steady: mostly on, with brief dips. */
@keyframes energy-flicker {
  0%,
  100% {
    opacity: 1;
  }

  8% {
    opacity: 0.8;
  }

  10% {
    opacity: 1;
  }

  41% {
    opacity: 0.9;
  }

  43% {
    opacity: 0.6;
  }

  45% {
    opacity: 1;
  }

  72% {
    opacity: 0.85;
  }

  74% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .energy__bulb-glass,
  .energy__rays,
  .energy__shine,
  .energy__bolt {
    animation: none;
  }
}
</style>
