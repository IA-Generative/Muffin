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

// Where the passage is on the page: the zones to frame on its screenshot. Never throws - a page with no
// positioned text (a Markdown page, a document indexed before this existed), a passage that is not found, or
// a backend that does not answer all give no zone, and the page is shown without a frame.
export async function fetchPageRects(
  collectionId: string,
  documentId: string,
  pageNumber: number,
  passage: string | undefined,
): Promise<PageRect[]> {
  if (!passage?.trim()) return []
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}/pages/${pageNumber}/highlights`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: passage }),
      },
    )
    if (!response.ok) return []
    const body: HighlightsOut = await response.json()
    return body.rects.map((rect) => ({ xMin: rect.x_min, yMin: rect.y_min, xMax: rect.x_max, yMax: rect.y_max }))
  } catch {
    return []
  }
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
