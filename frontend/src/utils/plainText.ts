import DOMPurify from 'dompurify'
import { marked } from 'marked'

// Strips markdown (tables, `code`, **bold**, [1] citation footnotes) down to something safe to
// read aloud - reading the raw syntax/brackets literally would be jarring for TTS. Reuses the
// same marked/DOMPurify pipeline ChatMessage.vue already renders with, then reads back the
// rendered DOM's textContent, which naturally collapses table cells and strips tags.
export function toPlainText(markdown: string): string {
  const html = DOMPurify.sanitize(marked.parse(markdown, { async: false }))
  const container = document.createElement('div')
  container.innerHTML = html
  return (container.textContent ?? '')
    .replace(/\[\d+(?:,\s*\d+)*\]/g, '') // [1] / [1,2] citation footnotes
    .replace(/\s+/g, ' ')
    .trim()
}
