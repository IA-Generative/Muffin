import type { Tool } from '../types/tool'

// À partir de ce nombre d'outils, la recherche passe par le serveur (recherche hybride sur les descriptions) ; en
// dessous, on filtre ici, sur les mots, sans aucune requête : peu d'outils n'ont pas besoin d'un vecteur. Doit rester
// égal à TOOLS_SEARCH_INDEX_MIN côté serveur (8 par défaut).
export const SERVER_SEARCH_FROM = 8
export const MIN_QUERY_LENGTH = 2
export const SEARCH_DELAY_MS = 300

type Searchable = Pick<Tool, 'name' | 'description' | 'inputSchema'>

// Les mots trop courants pour dire ce qu'un outil fait : « des » ne doit pas faire trouver tout ce qui contient « des ».
const STOP_WORDS = new Set(
  'le la les un une des de du et ou en au aux ce ces cet cette pour par sur sous avec dans que qui quoi est sont il elle ils je tu nous vous mon ma mes ton ta tes son sa ses pas ne se si the and for with'.split(' '),
)

function words(text: string): string[] {
  return (
    text
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .match(/[a-z0-9]{2,}/g)
      ?.filter((word) => !STOP_WORDS.has(word)) ?? []
  )
}

// Ce que dit un outil de lui-même : son nom, sa description et le nom de ses paramètres. Jamais une valeur.
export function searchableText(tool: Searchable): string {
  const properties = tool.inputSchema?.properties
  const parameters = properties && typeof properties === 'object' ? Object.keys(properties) : []
  return [tool.name.replace(/[_-]/g, ' '), tool.description, ...parameters].join(' ')
}

// Part des mots de la question qui commencent un mot de l'outil (« devise » trouve « devises »), comme le serveur.
export function lexicalScore(query: string, tool: Searchable): number {
  const wanted = [...new Set(words(query))]
  if (!wanted.length) return 0
  const own = words(searchableText(tool))
  const found = wanted.filter((word) => own.some((candidate) => candidate.startsWith(word) || word.startsWith(candidate)))
  return found.length / wanted.length
}

export function filterLocally<T extends Searchable>(tools: T[], query: string): T[] {
  return tools
    .map((tool) => ({ tool, score: lexicalScore(query, tool) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.tool.name.localeCompare(b.tool.name, 'fr'))
    .map((item) => item.tool)
}

// Une requête au serveur n'est faite que si elle apporte quelque chose : assez de caractères, et assez d'outils.
export function needsServerSearch(query: string, toolCount: number): boolean {
  return query.trim().length >= MIN_QUERY_LENGTH && toolCount >= SERVER_SEARCH_FROM
}
