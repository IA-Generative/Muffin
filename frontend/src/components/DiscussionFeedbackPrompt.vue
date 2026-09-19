<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useChat } from '../composables/useChat'

const props = defineProps<{
  messageCount: number
  conversationId: string
}>()

const emit = defineEmits<{
  open: []
}>()

const { activeDiscussionScores } = useChat()

// Show the prompt after this many assistant turns (each turn = 1 user + 1 assistant message).
const MIN_TURNS = 4
// Probability of showing the prompt once the threshold is reached (for testing: always after N turns,
// but with a chance to skip so it doesn't feel nagging on every conversation).
const TRIGGER_PROBABILITY = 0.5

// Track which conversations we've already prompted for, so we don't re-show after dismissal.
const promptedConversations = new Set<string>()
// Track the conversation we're currently showing the prompt for.
const visible = ref(false)

// Count assistant turns (every 2 messages = 1 turn, roughly).
const assistantTurns = computed(() =>
  Math.floor(props.messageCount / 2),
)

watch(
  () => [props.conversationId, props.messageCount] as const,
  ([convId, count], prev) => {
    // Reset when switching conversations.
    if (prev && prev[0] !== convId) {
      visible.value = false
      promptedConversations.delete(prev[0])
    }

    if (visible.value) return
    if (promptedConversations.has(convId)) return
    if (assistantTurns.value < MIN_TURNS) return

    // Only trigger on new messages, not on initial load of an old conversation.
    if (prev && prev[1] === count) return

    // Don't prompt if there are already discussion scores for this conversation.
    if (activeDiscussionScores.value.length > 0) return

    promptedConversations.add(convId)

    // Roll the dice — for testing, always after N turns but with a probability.
    if (Math.random() < TRIGGER_PROBABILITY) {
      visible.value = true
    }
  },
  { immediate: true },
)

function dismiss() {
  visible.value = false
}

function accept() {
  visible.value = false
  emit('open')
}
</script>

<template>
  <Transition name="prompt-slide">
    <div v-if="visible" class="discussion-prompt">
      <p class="discussion-prompt__text">
        Comment se passe cette discussion ? Votre avis nous aide à améliorer la qualité.
      </p>
      <div class="discussion-prompt__actions">
        <button type="button" class="fr-btn fr-btn--sm" @click="accept">
          Évaluer
        </button>
        <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="dismiss">
          Plus tard
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.discussion-prompt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  max-width: 48rem;
  margin: 0 auto 0.5rem;
  padding: 0.625rem 1rem;
  border-radius: 1rem;
  border: 1px solid var(--border-action-high-blue-france);
  background: var(--background-alt-blue-france);
  color: var(--text-action-high-blue-france);
  font-size: 0.8125rem;
}

.discussion-prompt__text {
  margin: 0;
  line-height: 1.4;
}

.discussion-prompt__actions {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

.prompt-slide-enter-active,
.prompt-slide-leave-active {
  transition: all 0.25s ease;
}

.prompt-slide-enter-from,
.prompt-slide-leave-to {
  opacity: 0;
  transform: translateY(0.5rem);
}
</style>
