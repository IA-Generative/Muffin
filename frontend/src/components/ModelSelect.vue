<script setup lang="ts">
// Le choix d'un modèle de chat. Sans choix (''), le serveur prend le premier modèle disponible : c'est dit, et
// proposé seulement tant que rien n'a été choisi (un modèle choisi ne peut plus redevenir « par défaut »).
import { computed } from 'vue'
import { useModels } from '../composables/useModels'

const props = defineProps<{ id: string; modelValue: string; describedby?: string; mixed?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const MIXED = '__mixed__'
const { models, isLoading, error } = useModels()
const ids = computed(() => {
  const known = models.value.map((model) => model.id)
  return props.modelValue && !known.includes(props.modelValue) ? [props.modelValue, ...known] : known
})
</script>

<template>
  <select
    :id="id"
    :value="mixed ? MIXED : modelValue"
    class="fr-select"
    :disabled="isLoading"
    :aria-describedby="describedby"
    @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
  >
    <option v-if="mixed" :value="MIXED" disabled>Plusieurs modèles (voir les réglages avancés)</option>
    <option v-if="modelValue === '' && !mixed" value="">Modèle par défaut du serveur</option>
    <option v-for="model in ids" :key="model" :value="model">{{ model }}</option>
  </select>
  <p v-if="error" class="sf-hint">{{ error }}</p>
</template>
