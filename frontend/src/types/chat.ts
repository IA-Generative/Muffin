import type { LiveStep } from '../utils/runSteps'
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
  // Names from the root down to the cited collection, through collections the user can read (#220).
  collectionPath?: string[]
  documentId?: string
  // The cited chunk, for a "document" citation (#353): what the backend locates in its pages.
  chunkId?: string
  pageNumber?: number
  // Only for a citation of a living document (#171): which revision of it the answer was drawn from.
  revision?: number
  query?: string
  content?: string
  // The passage of the excerpt the answer rests on (#402), as the excerpt has it - verified by the backend, never
  // the model's copy. Absent when the model named none or the one it named is not in the excerpt.
  quote?: string
  // Only for a "qa" citation (#351): where the cited pair's answer comes from - the document, page and passage
  // that open on that page with the passage framed. `start`/`end` is where the passage is in the page's text,
  // when known. Absent for a pair written by hand, or with no passage found.
  qaSource?: {
    documentId: string
    documentName: string
    pageNumber: number
    passage: string
    start?: number
    end?: number
  }
}

// A change to a living document that the research agent delegated to the editing agent (#171) -
// what the chat needs to show the proposal next to the answer. The proposal itself (preview,
// verdict, validate/adjust/refuse) lives on the backend and is read through the document's draft.
export interface EditProposal {
  collectionId: string
  documentId: string
  documentName: string
}

// A new Markdown document the research agent wrote and proposed to create in one of the user's
// collections. It exists nowhere until the user creates it from the card: `status` follows what
// they decided, and survives a reload (it is stored with the run).
export interface CreationProposal {
  status: 'pending' | 'created' | 'refused'
  collectionId: string
  collectionName: string
  // The document's title, which becomes its file name (the backend adds the .md).
  name: string
  content: string
  // Set once created.
  documentId?: string
}

// A multiple-choice question the assistant asked instead of answering (#344), and the user's answer
// to it: options picked (by label) and/or free text. A question with no options is answered in text only.
export interface QuestionOption {
  label: string
  description: string
}

export interface AssistantQuestion {
  question: string
  // The tab the question gets: a word or two.
  header: string
  multiSelect: boolean
  options: QuestionOption[]
}

export interface QuestionAnswer {
  selected: string[]
  text: string
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
  // True while a pending message shows the answer as it is being written (content is then markdown, the
  // answer so far) rather than a step label.
  streaming?: boolean
  // The steps of the run behind a pending message, as they happen (its events, read as lines).
  steps?: LiveStep[]
  // True when this message is an error (run failed, network error, etc.) - ChatMessage.vue
  // renders it with a distinct error style (icon + color) instead of a normal assistant bubble.
  // The technical error from the backend (run.error) is never shown to the user - only a clean
  // French message is, so a 500 with a stack trace or FK violation detail doesn't leak through.
  error?: boolean
  // The feedback value (up/down) the current user left on this message, if any - restored
  // from the backend after a page reload so the thumbs-up/down button stays highlighted.
  feedback?: 'up' | 'down' | null
  // Set when this answer comes with a proposed edit of a living document - shown as its own card
  // below the answer, clearly apart from it.
  editProposal?: EditProposal
  // Set when this answer comes with a new Markdown document to create - its own card, like the above.
  creationProposal?: CreationProposal
  // Collections whose sub-collections the run behind this answer didn't explore (#219, #233) -
  // the latest answer offers to "go further" into them.
  unexploredCollectionIds?: string[]
  // The answer rests on consulted excerpts but cites none of them (#402): the chat says it has no source.
  noSources?: boolean
  // The assistant the chat was made with (#514), as it was named when this answer was written.
  assistantName?: string
  // The questions this message asks instead of answering (#344) - shown as a card to answer. Once the
  // user answered, `questionsAnswer` holds the answer (the card stays in the thread with it); if they
  // wrote something else instead, the questions are `questionsAbandoned`.
  questions?: AssistantQuestion[]
  questionsAnswer?: QuestionAnswer[]
  questionsAbandoned?: boolean
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

export interface FilingSuggestionCandidate {
  collectionId: string
  collectionName: string
  collectionDescription: string
  score: number
}

export interface ConversationFile {
  id: string
  name: string
  // 'queued': selected before this conversation has a real backend id yet (see useChat.ts's
  // attachFile) - uploaded automatically once the first message creates one, never a real
  // backend status. The rest mirror CollectionDocument's indexing pipeline.
  status: 'queued' | 'pending' | 'indexing' | 'indexed' | 'error'
  progress: number
  // Filing suggestion (§122) - set once this file's summary is ready, if a matching collection
  // was found among the ones the uploader owns. Never set on a 'queued'/'pending' chip (no
  // summary yet), and filingDismissed silences the notification without changing anything else.
  suggestedCollectionId?: string
  suggestedCollectionName?: string
  suggestedCollectionScore?: number
  filingCandidates: FilingSuggestionCandidate[]
  filingDismissed: boolean
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
