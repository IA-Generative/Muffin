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
