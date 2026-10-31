// The search of the conversations (#509): what is typed, and how a result is shown.

export const MIN_QUERY_LENGTH = 2

// Marks the words found in a snippet. Control characters, not markup: the backend never builds HTML from a message, and
// a snippet is only ever cut here and drawn as text.
const HIGHLIGHT_START = '\u0002'
const HIGHLIGHT_END = '\u0003'

export interface SnippetPart {
  text: string
  match: boolean
}

export function normalizeQuery(query: string): string {
  return query.trim().replace(/\s+/g, ' ')
}

// Whether a query is long enough to be sent: shorter ones match nearly everything.
export function isSearchable(query: string): boolean {
  return normalizeQuery(query).length >= MIN_QUERY_LENGTH
}

// A passage as a list of pieces, the words found flagged. The citation markers of an answer ("[a1b2c3]") mean nothing
// out of their context and are left out, and the line breaks are folded: a snippet is one line of the sidebar.
export function snippetParts(snippet: string): SnippetPart[] {
  const text = snippet.replace(/\s?\[[^\]\s]+\]/g, '').replace(/\s+/g, ' ').trim()
  const parts: SnippetPart[] = []
  let match = false
  let current = ''
  for (const char of text) {
    if (char === HIGHLIGHT_START || char === HIGHLIGHT_END) {
      if (current) parts.push({ text: current, match })
      current = ''
      match = char === HIGHLIGHT_START
    } else {
      current += char
    }
  }
  if (current) parts.push({ text: current, match })
  return parts
}
