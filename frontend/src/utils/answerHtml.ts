import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { chartAltText, chartImageUrl } from './chartImages'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// The HTML of an answer written in Markdown: parsed, sanitized, and its images restricted to the charts the backend serves
// (#434). Done on an inert document - the browser loads nothing from it - so an image that is refused is never requested.
export function answerHtml(markdown: string): string {
  const sanitized = DOMPurify.sanitize(marked.parse(markdown, { async: false }))
  const inert = new DOMParser().parseFromString(sanitized, 'text/html')
  for (const image of Array.from(inert.querySelectorAll('img'))) {
    const url = chartImageUrl(image.getAttribute('src') ?? '', API_BASE_URL)
    if (url === null) {
      // Not a chart: the text that stood for it, if any, is all that stays.
      image.replaceWith(inert.createTextNode(image.getAttribute('alt') ?? ''))
      continue
    }
    const alt = chartAltText(image.getAttribute('alt'))
    for (const name of image.getAttributeNames()) image.removeAttribute(name)
    image.setAttribute('src', url)
    image.setAttribute('alt', alt)
    image.setAttribute('loading', 'lazy')
    image.setAttribute('class', 'chat-chart')
    // A chart opens larger on a click or a key (ChatMessage): it is then a button for the keyboard and the readers.
    image.setAttribute('role', 'button')
    image.setAttribute('tabindex', '0')
    image.setAttribute('title', 'Agrandir le graphique')
  }
  return inert.body.innerHTML
}
