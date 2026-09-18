export interface Source {
  title: string
  // Optional: a real run's citations point at a document/knowledge-base id,
  // not a browsable URL - only mocked/user-added sources have one.
  url?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  // The research run that produced this message, if any (assistant messages only) - lets the
  // UI fetch that run's step-by-step event trace ("execution detail") on demand.
  runId?: string
  // True while this message is a run-in-progress placeholder (content is a step label, e.g.
  // "Analyse de votre question") - ChatMessage.vue shows an animated "…" after it instead of a
  // static one, and never renders it as markdown.
  pending?: boolean
}

export interface ExecutionEvent {
  id: string
  label: string
  taskId?: string
  createdAt: string
}

export interface FeedbackDetails {
  reasons: string[]
  comment: string
  validatedSources: string[]
  addedSources: Source[]
}

export interface Conversation {
  id: string
  title: string
}
