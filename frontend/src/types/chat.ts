export interface Source {
  title: string
  // The backend Source row this citation was materialized into (see the backend's
  // SourceRepository.link_citations) - only set for a "document"/"web" citation, since those are
  // the only ones with a stable identity worth persisting. Absent for a "tool" citation, an
  // older citation persisted before this existed, or a feedback's own addedSources (a brand-new
  // suggestion, not a Source yet). This is what FeedbackModal.vue sends back as
  // validatedSourceIds - never the title/url, which aren't guaranteed unique or stable.
  id?: string
  // Set for a "web" citation (the web_search tool - a real, browsable external URL, see
  // useChat.ts's formatAnswerWithCitations) or an older/mocked/user-added source.
  url?: string
  // The rest are only set for a real citation (never a user-added feedback source) - see
  // useChat.ts's formatAnswerWithCitations. "document" citations ("search"/"page_content" tools)
  // link back to a real page + the exact chunk text; "web" ones (web_search) link to `url`
  // instead; every other tool is just input/output, there's nothing to open for either.
  type?: 'document' | 'document_summary' | 'qa' | 'collection' | 'tool' | 'web'
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
  // True when this message is an error (run failed, network error, etc.) - ChatMessage.vue
  // renders it with a distinct error style (icon + color) instead of a normal assistant bubble.
  // The technical error from the backend (run.error) is never shown to the user - only a clean
  // French message is, so a 500 with a stack trace or FK violation detail doesn't leak through.
  error?: boolean
  // The feedback value (up/down) the current user left on this message, if any - restored
  // from the backend after a page reload so the thumbs-up/down button stays highlighted.
  feedback?: 'up' | 'down' | null
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
  // Backend Source.id values (see Source.id above) - only ever sources that actually have one,
  // FeedbackModal.vue never offers "valider" for a source without a stable id to send.
  validatedSourceIds: string[]
  addedSources: Source[]
}

export interface Conversation {
  id: string
  title: string
}

export interface ConversationFile {
  id: string
  name: string
  // 'queued': selected before this conversation has a real backend id yet (see useChat.ts's
  // attachFile) - uploaded automatically once the first message creates one, never a real
  // backend status. The rest mirror CollectionDocument's indexing pipeline.
  status: 'queued' | 'pending' | 'indexing' | 'indexed' | 'error'
  progress: number
}

export interface DiscussionScore {
  id: string
  conversationId: string
  createdAt: string
  messageCount: number
  llmModel: string
  coherent: boolean
  coherenceIssues: string[]
  contextUsageScore: number
  contextUsageIssues: string[]
  reasoning: string | null
}

export interface DiscussionFeedback {
  id: string
  conversationId: string
  userId: string
  rating: number
  coherent: boolean
  contextUsageScore: number | null
  comment: string | null
  createdAt: string
  updatedAt: string
}
