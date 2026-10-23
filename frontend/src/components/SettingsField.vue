<script setup lang="ts">
// Un champ de formulaire accessible : l'étiquette, l'aide et l'erreur sont reliées au contrôle (aria-describedby,
// aria-invalid) sans que chaque appelant ait à le refaire. Le contrôle va dans le slot et reçoit ce qu'il lui faut.
import { computed } from 'vue'
import '../assets/settings-form.css'

const props = defineProps<{
  id: string
  label: string
  hint?: string
  error?: string
  optional?: boolean
  short?: boolean
}>()

defineSlots<{ default(props: { id: string; describedby: string | undefined; invalid: 'true' | undefined }): unknown }>()

const hintId = computed(() => (props.hint ? `${props.id}-hint` : undefined))
const errorId = computed(() => (props.error ? `${props.id}-error` : undefined))
const describedby = computed(() => [hintId.value, errorId.value].filter(Boolean).join(' ') || undefined)
</script>

<template>
  <div class="sf-field" :class="{ 'sf-field--short': short }">
    <label :for="id" class="sf-label">
      {{ label }}<span v-if="optional" class="sf-optional"> (facultatif)</span>
    </label>
    <slot :id="id" :describedby="describedby" :invalid="error ? ('true' as const) : undefined" />
    <p v-if="hint" :id="hintId" class="sf-hint">{{ hint }}</p>
    <p v-if="error" :id="errorId" class="sf-error">{{ error }}</p>
  </div>
</template>
