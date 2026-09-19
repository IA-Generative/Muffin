export interface Source {
  title: string
  // Set for a "web" citation (the web_search tool - a real, browsable external URL, see
  // useChat.ts's formatAnswerWithCitations) or an older/mocked/user-added source.
  url?: string
  // The rest are only set for a real citation (never a user-added feedback source) - see
  // useChat.ts's formatAnswerWithCitations. "document" citations ("search"/"page_content" tools)
  // link back to a real page + the exact chunk text; "web" ones (web_search) link to `url`
  // instead; every other tool is just input/output, there's nothing to open for either.
  type?: 'document' | 'tool' | 'web'
  collectionId?: string
  documentId?: string
  pageNumber?: number
  query?: string
  content?: string
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
