import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { AssistantQuestion } from '../types/chat.ts'
import { allAnswered, emptyAnswers, formatAnswers, toggleOption, toRequestAnswers } from './questionAnswers.ts'

const single: AssistantQuestion = {
  question: 'Quelle période ?',
  header: 'Période',
  multiSelect: false,
  options: [
    { label: '2023', description: '' },
    { label: '2024', description: '' },
  ],
}
const multiple: AssistantQuestion = {
  question: 'Quels services ?',
  header: 'Services',
  multiSelect: true,
  options: [
    { label: 'RH', description: '' },
    { label: 'Finance', description: '' },
  ],
}

test('a new card has nothing answered', () => {
  const answers = emptyAnswers([single, multiple])

  assert.equal(answers.length, 2)
  assert.equal(allAnswered([single, multiple], answers), false)
})

test('a single choice keeps one option and clears it when picked again', () => {
  let answer = emptyAnswers([single])[0]

  answer = toggleOption(single, answer, '2023')
  answer = toggleOption(single, answer, '2024')
  assert.deepEqual(answer.selected, ['2024'])

  answer = toggleOption(single, answer, '2024')
  assert.deepEqual(answer.selected, [])
})

test('a multiple choice toggles each option', () => {
  let answer = emptyAnswers([multiple])[0]

  answer = toggleOption(multiple, answer, 'RH')
  answer = toggleOption(multiple, answer, 'Finance')
  assert.deepEqual(answer.selected, ['RH', 'Finance'])

  answer = toggleOption(multiple, answer, 'RH')
  assert.deepEqual(answer.selected, ['Finance'])
})

test('a question is answered by an option or by free text, not by blanks', () => {
  const questions = [single, multiple]

  assert.equal(allAnswered(questions, [{ selected: ['2024'], text: '' }, { selected: [], text: '   ' }]), false)
  assert.equal(allAnswered(questions, [{ selected: ['2024'], text: '' }, { selected: [], text: 'les deux' }]), true)
  assert.equal(allAnswered([], []), false)
  assert.equal(allAnswered(questions, [{ selected: ['2024'], text: '' }]), false)
})

test('the answer reads as each question with what was chosen and written', () => {
  const text = formatAnswers(
    [single, multiple],
    [
      { selected: ['2024'], text: '' },
      { selected: ['RH', 'Finance'], text: ' pas la direction ' },
    ],
  )

  assert.equal(text, 'Quelle période ? → 2024\nQuels services ? → RH, Finance ; pas la direction')
})

test('the request carries free text only when there is some', () => {
  assert.deepEqual(
    toRequestAnswers([
      { selected: ['2024'], text: '  ' },
      { selected: [], text: ' autre ' },
    ]),
    [
      { selected: ['2024'], text: null },
      { selected: [], text: 'autre' },
    ],
  )
})
