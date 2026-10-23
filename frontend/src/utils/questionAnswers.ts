import type { AssistantQuestion, QuestionAnswer } from '../types/chat'

export function emptyAnswers(questions: AssistantQuestion[]): QuestionAnswer[] {
  return questions.map(() => ({ selected: [], text: '' }))
}

// A question is answered by an option, or by free text - or both (a precision next to the choice).
export function isAnswered(answer: QuestionAnswer): boolean {
  return answer.selected.length > 0 || answer.text.trim() !== ''
}

export function allAnswered(questions: AssistantQuestion[], answers: QuestionAnswer[]): boolean {
  return questions.length > 0 && questions.every((_, index) => !!answers[index] && isAnswered(answers[index]))
}

// A single-choice question keeps one option (picking it again clears it); a multiple-choice one toggles each.
export function toggleOption(question: AssistantQuestion, answer: QuestionAnswer, label: string): QuestionAnswer {
  const picked = answer.selected.includes(label)
  if (question.multiSelect) {
    return { ...answer, selected: picked ? answer.selected.filter((item) => item !== label) : [...answer.selected, label] }
  }
  return { ...answer, selected: picked ? [] : [label] }
}

// What the user's message says in the thread, and so what the next run reads: each question with its answer.
export function formatAnswers(questions: AssistantQuestion[], answers: QuestionAnswer[]): string {
  return questions
    .map((question, index) => {
      const answer = answers[index]
      const parts = [answer.selected.join(', '), answer.text.trim()].filter((part) => part !== '')
      return `${question.question} → ${parts.join(' ; ')}`
    })
    .join('\n')
}

// The answer as the backend takes it (blanks trimmed, free text absent rather than empty).
export function toRequestAnswers(answers: QuestionAnswer[]): { selected: string[]; text: string | null }[] {
  return answers.map((answer) => ({ selected: answer.selected, text: answer.text.trim() || null }))
}
