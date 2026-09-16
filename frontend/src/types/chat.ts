export interface Source {
  title: string
  url: string
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
