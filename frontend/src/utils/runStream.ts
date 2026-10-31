// The live stream of a run (#510): what a message of it means for the chat.

export interface AnswerDelta {
  text: string
  // The text is the whole answer so far, to put in place of what is shown: what looked like its start was not.
  replace?: boolean
}

// The statuses after which the run has nothing more to show: its stream is closed and the run itself is read.
const ENDING_STATUSES = new Set(['completed', 'failed', 'cancelled', 'waiting_for_user'])

export function isEndingStatus(status: string): boolean {
  return ENDING_STATUSES.has(status)
}

// The answer shown so far, once a piece of it has come.
export function applyDelta(shown: string, delta: AnswerDelta): string {
  return delta.replace ? delta.text : shown + delta.text
}
