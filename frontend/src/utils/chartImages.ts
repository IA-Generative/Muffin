// The charts the assistant draws (#434) are Markdown images that the backend serves, with the rights of the conversation:
// /api/conversations/{id}/charts/{id}.png. They are the only images an answer may show. Any other one is not loaded:
// the answer is written by a model that read documents anyone may have written, and an image from elsewhere is a
// request to wherever it says, carrying whatever was put in its address.

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
const CHART_PATH = new RegExp(`^/api/conversations/${UUID}/charts/${UUID}\\.png$`, 'i')

// The address to load a chart from, or null when `src` is not a chart of the backend. Absolute only if it is the API's own origin.
export function chartImageUrl(src: string, apiBaseUrl: string): string | null {
  const base = apiBaseUrl.replace(/\/+$/, '')
  const path = src.startsWith(`${base}/`) ? src.slice(base.length) : src
  return CHART_PATH.test(path) ? `${base}${path}` : null
}

// The alternative text of a chart: its title, or a generic one.
export function chartAltText(alt: string | null | undefined): string {
  const text = (alt ?? '').trim()
  return text ? `Graphique : ${text}` : 'Graphique'
}
