const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// One occurrence of an entity in the text (#352): the document and page it is on, and where in that page.
export interface EntityMention {
  documentId: string
  documentName: string
  pageNumber: number
  start: number
  end: number
}

interface MentionOut {
  document_id: string
  document_name: string
  page_number: number
  start: number
  end: number
}

// The occurrences of an entity, in the order one reads them - in one document when asked. Throws when the
// backend does not answer: the caller says so, rather than showing "no occurrence" for a failure.
export async function fetchEntityMentions(
  collectionId: string,
  entityId: string,
  documentId?: string,
): Promise<EntityMention[]> {
  const query = documentId ? `?document_id=${documentId}` : ''
  const response = await fetch(`${API_BASE_URL}/api/collections/${collectionId}/entities/${entityId}/mentions${query}`, {
    credentials: 'include',
  })
  if (!response.ok) throw new Error(`${response.status}`)
  const body: MentionOut[] = await response.json()
  return body.map((mention) => ({
    documentId: mention.document_id,
    documentName: mention.document_name,
    pageNumber: mention.page_number,
    start: mention.start,
    end: mention.end,
  }))
}
