const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// A zone to frame on a page's screenshot, normalized between 0 and 1 against the page (#350).
export interface PageRect {
  xMin: number
  yMin: number
  xMax: number
  yMax: number
}

interface HighlightsOut {
  rects: { x_min: number; y_min: number; x_max: number; y_max: number }[]
}

// What to frame: a passage, found in the page's text - or, when it is known, the exact interval of characters of it.
export type Passage = string | { start: number; end: number }

// Where the passage is on the page: the zones to frame on its screenshot. Never throws - a page with no
// positioned text (a Markdown page, a document indexed before this existed), a passage that is not found, or
// a backend that does not answer all give no zone, and the page is shown without a frame.
export async function fetchPageRects(
  collectionId: string,
  documentId: string,
  pageNumber: number,
  passage: Passage | undefined,
): Promise<PageRect[]> {
  const body = typeof passage === 'string' ? { text: passage } : passage
  if (!body || (typeof passage === 'string' && !passage.trim())) return []
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}/pages/${pageNumber}/highlights`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    if (!response.ok) return []
    const out: HighlightsOut = await response.json()
    return out.rects.map((rect) => ({ xMin: rect.x_min, yMin: rect.y_min, xMax: rect.x_max, yMax: rect.y_max }))
  } catch {
    return []
  }
}

// The zones of a cited passage: at the exact interval of characters when it is known (a question-answer pair
// remembers where its passage is, #351), and, when that gives nothing - the page changed since - by looking for
// the passage's text.
export async function fetchSourceRects(
  collectionId: string,
  documentId: string,
  pageNumber: number,
  source: { passage?: string; start?: number; end?: number },
): Promise<PageRect[]> {
  if (source.start !== undefined && source.end !== undefined) {
    const exact = await fetchPageRects(collectionId, documentId, pageNumber, { start: source.start, end: source.end })
    if (exact.length) return exact
  }
  return fetchPageRects(collectionId, documentId, pageNumber, source.passage)
}

// The style of a zone, in percent of the image it is laid over.
export function rectStyle(rect: PageRect): Record<string, string> {
  return {
    left: `${rect.xMin * 100}%`,
    top: `${rect.yMin * 100}%`,
    width: `${(rect.xMax - rect.xMin) * 100}%`,
    height: `${(rect.yMax - rect.yMin) * 100}%`,
  }
}
