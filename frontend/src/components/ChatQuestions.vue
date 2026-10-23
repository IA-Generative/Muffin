<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useChat } from '../composables/useChat'
import type { ChatMessage, QuestionAnswer } from '../types/chat'
import { allAnswered, emptyAnswers, isAnswered, toggleOption } from '../utils/questionAnswers'

const props = defineProps<{ message: ChatMessage }>()

const { answerQuestions } = useChat()

const questions = computed(() => props.message.questions ?? [])
const answers = ref<QuestionAnswer[]>(emptyAnswers(questions.value))
const current = ref(0)
const sending = ref(false)

// What the thread says about the card: still to answer, answered (with what was said), or let go.
const answered = computed(() => props.message.questionsAnswer !== undefined)
const abandoned = computed(() => !answered.value && !!props.message.questionsAbandoned)
const open = computed(() => !answered.value && !abandoned.value)
const complete = computed(() => allAnswered(questions.value, answers.value))
const missing = computed(() => answers.value.filter((answer) => !isAnswered(answer)).length)

// Ids tie each tab to its panel (and each field to its label); the message id keeps them unique per card.
const base = computed(() => `questions-${props.message.id}`)

function pick(index: number, label: string) {
  answers.value[index] = toggleOption(questions.value[index], answers.value[index], label)
}

function setText(index: number, text: string) {
  answers.value[index] = { ...answers.value[index], text }
}

async function goTo(index: number) {
  current.value = (index + questions.value.length) % questions.value.length
  await nextTick()
  document.getElementById(`${base.value}-tab-${current.value}`)?.focus()
}

// The keys of a tab list: arrows move between tabs (wrapping), Home and End jump to the ends.
function onTabKey(event: KeyboardEvent) {
  const moves: Record<string, number> = {
    ArrowRight: current.value + 1,
    ArrowLeft: current.value - 1,
    Home: 0,
    End: questions.value.length - 1,
  }
  if (!(event.key in moves)) return
  event.preventDefault()
  goTo(moves[event.key])
}

async function send() {
  if (!complete.value || sending.value) return
  sending.value = true
  try {
    await answerQuestions(props.message.id, answers.value)
  } finally {
    sending.value = false
  }
}

function answerText(answer: QuestionAnswer | undefined): string {
  if (!answer) return ''
  return [answer.selected.join(', '), answer.text.trim()].filter((part) => part !== '').join(' ; ')
}
</script>

<template>
  <section class="questions" :class="{ 'questions--closed': !open }" aria-label="Questions de l’assistant">
    <!-- Answered or let go: the card stays in the thread, read-only. -->
    <template v-if="!open">
      <p class="questions__state">
        {{ answered ? 'Vous avez répondu à ces questions.' : 'Ces questions sont restées sans réponse.' }}
      </p>
      <dl class="questions__summary">
        <template v-for="(question, index) in questions" :key="index">
          <dt>{{ question.question }}</dt>
          <dd v-if="answered">{{ answerText(message.questionsAnswer?.[index]) }}</dd>
        </template>
      </dl>
    </template>

    <template v-else>
      <div v-if="questions.length > 1" class="questions__tabs" role="tablist" aria-label="Questions" @keydown="onTabKey">
        <button
          v-for="(question, index) in questions"
          :id="`${base}-tab-${index}`"
          :key="index"
          type="button"
          role="tab"
          class="questions__tab"
          :class="{ 'questions__tab--current': index === current }"
          :aria-selected="index === current"
          :aria-controls="`${base}-panel-${index}`"
          :tabindex="index === current ? 0 : -1"
          @click="current = index"
        >
          {{ question.header }}
          <span v-if="isAnswered(answers[index])" class="questions__done" aria-hidden="true">✓</span>
          <span v-if="isAnswered(answers[index])" class="fr-sr-only"> (répondu)</span>
        </button>
      </div>

      <div
        v-for="(question, index) in questions"
        v-show="index === current"
        :id="`${base}-panel-${index}`"
        :key="index"
        class="questions__panel"
        :role="questions.length > 1 ? 'tabpanel' : undefined"
        :aria-labelledby="questions.length > 1 ? `${base}-tab-${index}` : undefined"
      >
        <fieldset class="fr-fieldset questions__fieldset" :aria-describedby="question.options.length ? `${base}-hint-${index}` : undefined"
        >
          <legend class="fr-fieldset__legend questions__legend">{{ question.question }}</legend>
          <p v-if="question.options.length" :id="`${base}-hint-${index}`" class="fr-hint-text questions__hint">
            {{ question.multiSelect ? 'Plusieurs réponses possibles.' : 'Une seule réponse possible.' }}
          </p>
          <div v-for="(option, optionIndex) in question.options" :key="option.label" class="fr-fieldset__element">
            <div :class="question.multiSelect ? 'fr-checkbox-group fr-checkbox-group--sm' : 'fr-radio-group fr-radio-group--sm'">
              <input
                :id="`${base}-${index}-${optionIndex}`"
                :type="question.multiSelect ? 'checkbox' : 'radio'"
                :name="`${base}-${index}`"
                :value="option.label"
                :checked="answers[index].selected.includes(option.label)"
                @click="pick(index, option.label)"
              />
              <label class="fr-label" :for="`${base}-${index}-${optionIndex}`">
                {{ option.label }}
                <span v-if="option.description" class="fr-hint-text">{{ option.description }}</span>
              </label>
            </div>
          </div>
        </fieldset>

        <div class="fr-input-group questions__free">
          <label class="fr-label" :for="`${base}-text-${index}`">
            {{ question.options.length ? 'Autre réponse ou précision (facultatif)' : 'Votre réponse' }}
          </label>
          <input
            :id="`${base}-text-${index}`"
            class="fr-input"
            type="text"
            maxlength="2000"
            :value="answers[index].text"
            @input="setText(index, ($event.target as HTMLInputElement).value)"
          />
        </div>
      </div>

      <div class="questions__actions">
        <button type="button" class="fr-btn fr-btn--sm" :disabled="!complete || sending" @click="send">Envoyer mes réponses</button>
        <p v-if="!complete" class="questions__missing" role="status">
          {{ missing === 1 ? '1 question sans réponse' : `${missing} questions sans réponse` }}
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.questions {
  width: 100%;
  max-width: 36rem;
  box-sizing: border-box;
  padding: 0.875rem 1rem;
  border: 1px solid var(--border-default-grey);
  border-left: 4px solid var(--border-action-high-blue-france);
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
  color: var(--text-default-grey);
}

.questions--closed {
  border-left-color: var(--border-default-grey);
}

.questions__state {
  margin: 0 0 0.5rem;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.questions__summary {
  margin: 0;
}

.questions__summary dt {
  font-weight: 600;
  margin-top: 0.5rem;
}

.questions__summary dd {
  margin: 0.125rem 0 0;
}

.questions__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-default-grey);
}

.questions__tab {
  padding: 0.375rem 0.75rem;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 0.25rem 0.25rem 0 0;
  background: none;
  color: var(--text-action-high-blue-france);
  font: inherit;
  font-size: 0.875rem;
  cursor: pointer;
}

.questions__tab--current {
  border-color: var(--border-default-grey);
  background: var(--background-default-grey);
  font-weight: 600;
}

.questions__done {
  margin-left: 0.25rem;
  color: var(--text-default-success);
}

.questions__fieldset {
  margin: 0 0 0.5rem;
  padding: 0;
  border: none;
}

.questions__legend {
  font-weight: 600;
}

.questions__hint {
  margin: 0 0 0.5rem;
}

.questions__free {
  margin-top: 0.25rem;
}

.questions__actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.questions__missing {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}
</style>
