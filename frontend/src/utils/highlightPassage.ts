export interface TextSegment {
  text: string
  highlighted: boolean
}

export interface PassageMatch {
  segments: TextSegment[]
  // At least one fragment of the passage was found on the page.
  matched: boolean
  // The passage's first / last fragment were found here. A passage that starts on a page and goes on
  // on the next one (a chunk cut across a page break) has its last fragment missing from the first.
  firstFound: boolean
  lastFound: boolean
}

const ELLIPSIS_EDGES = /^(?:\.{2,}|…|\s)+|(?:\.{2,}|…|\s)+$/g
// Fragments of a passage: its paragraphs - a chunk is paragraphs joined by blank lines, and each lies
// on one page - and the pieces an excerpt is truncated into with "...".
const FRAGMENT_SPLIT = /\n\s*\n|\.{2,}|…/
const MIN_MATCH = 3
const FIRST_WORDS = 8

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Tolerant: the words of the fragment separated by any whitespace (an excerpt is flattened, the
// page text keeps its line breaks), whatever the case.
function looseRegExp(fragment: string): RegExp | null {
  const words = fragment.split(/\s+/).filter(Boolean).map(escapeRegExp)
  return words.length ? new RegExp(words.join('\\s+'), 'i') : null
}

function find(content: string, fragment: string, from: number): [number, number] | null {
  // First the fragment whole, then its first words - an excerpt can be a summary of the zone, so
  // it may not match word for word.
  const candidates = [fragment, fragment.split(/\s+/).slice(0, FIRST_WORDS).join(' ')]
  for (const candidate of candidates) {
    const regex = looseRegExp(candidate)
    if (!regex) continue
    // After the previous fragment when it can be (they come in order); anywhere otherwise.
    for (const start of [from, 0]) {
      const match = regex.exec(content.slice(start))
      if (match && match[0].length >= MIN_MATCH) return [start + match.index, start + match.index + match[0].length]
    }
  }
  return null
}

/**
 * Splits a page's text into segments, highlighting the passage that was cited (the chunk, or the
 * evidence of a question-answer pair). With nothing found, nothing is highlighted - never a wrong
 * highlight.
 */
export function highlightPassage(content: string, passage: string | null | undefined): PassageMatch {
  const plain: PassageMatch = {
    segments: content ? [{ text: content, highlighted: false }] : [],
    matched: false,
    firstFound: false,
    lastFound: false,
  }
  const cleaned = (passage ?? '').replace(ELLIPSIS_EDGES, '').trim()
  if (!content || !cleaned) return plain

  const fragments = cleaned
    .split(FRAGMENT_SPLIT)
    .map((fragment) => fragment.trim())
    .filter(Boolean)
  const found: ([number, number] | null)[] = []
  let cursor = 0
  for (const fragment of fragments) {
    const range = find(content, fragment, cursor)
    found.push(range)
    if (range) cursor = range[1]
  }
  const ranges = found.filter((range): range is [number, number] => range !== null).sort((a, b) => a[0] - b[0])
  if (!ranges.length) return plain

  const segments: TextSegment[] = []
  let position = 0
  for (const [start, end] of ranges) {
    if (start < position) continue // overlaps the previous one
    if (start > position) segments.push({ text: content.slice(position, start), highlighted: false })
    segments.push({ text: content.slice(start, end), highlighted: true })
    position = end
  }
  if (position < content.length) segments.push({ text: content.slice(position), highlighted: false })
  return { segments, matched: true, firstFound: found[0] !== null, lastFound: found[found.length - 1] !== null }
}
