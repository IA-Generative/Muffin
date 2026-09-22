import { ref } from 'vue'

// Public repo (raw.githubusercontent.com serves permissive CORS headers for public repos, no
// backend proxy needed) - see docs/ui/user-menu/README.md for why this isn't routed through the
// backend instead (CHANGELOG.md lives at the repo root, outside the backend's own Docker build
// context).
const CHANGELOG_RAW_URL = 'https://raw.githubusercontent.com/IA-Generative/Muffin/main/CHANGELOG.md'
export const CHANGELOG_URL = 'https://github.com/IA-Generative/Muffin/blob/main/CHANGELOG.md'

const latestSection = ref<string | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
let fetched = false

// release-please always writes the newest release first (descending order) - the current
// version's own notes are just everything between the first "## [" heading and the second one.
function extractLatestSection(markdown: string): string | null {
  const headings = [...markdown.matchAll(/^## \[/gm)].map((match) => match.index ?? 0)
  if (headings.length === 0) return null
  const end = headings.length > 1 ? headings[1] : markdown.length
  return markdown.slice(headings[0], end).trim()
}

async function fetchLatestChangelog() {
  if (fetched) return
  fetched = true
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(CHANGELOG_RAW_URL)
    if (!response.ok) throw new Error(`${response.status}`)
    latestSection.value = extractLatestSection(await response.text())
  } catch {
    error.value = "Impossible de récupérer les notes de version."
  } finally {
    isLoading.value = false
  }
}

export function useChangelog() {
  return { latestSection, isLoading, error, fetchLatestChangelog }
}
