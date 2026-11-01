import type { Assistant } from '../types/assistant'

// À partir de ce nombre d'assistants lisibles, la recherche passe par le serveur (recherche hybride sur les descriptions) ;
// en dessous, on filtre ici, sur les mots, sans aucune requête : peu d'assistants n'ont pas besoin d'un vecteur.
// Doit rester égal à ASSISTANTS_SEARCH_INDEX_MIN côté serveur (8 par défaut).
export const SERVER_SEARCH_FROM = 8
export const MIN_QUERY_LENGTH = 2
export const SEARCH_DELAY_MS = 300

function words(text: string): string[] {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .match(/[a-z0-9]{2,}/g) ?? []
}

// Ce que dit un assistant de lui-même : son nom, sa description et ses questions suggérées. Jamais ses consignes, que
// l'auteur peut masquer : la recherche ne doit pas permettre de les deviner.
export function searchableText(assistant: Pick<Assistant, 'name' | 'description' | 'suggestions'>): string {
  return [assistant.name, assistant.description, ...assistant.suggestions].join(' ')
}

// Part des mots de la question qui commencent un mot de l'assistant (« congé » trouve « congés »), comme le serveur.
export function lexicalScore(query: string, assistant: Pick<Assistant, 'name' | 'description' | 'suggestions'>): number {
  const wanted = [...new Set(words(query))]
  if (!wanted.length) return 0
  const own = words(searchableText(assistant))
  const found = wanted.filter((word) => own.some((candidate) => candidate.startsWith(word) || word.startsWith(candidate)))
  return found.length / wanted.length
}

export function filterLocally<T extends Pick<Assistant, 'name' | 'description' | 'suggestions'>>(
  assistants: T[],
  query: string,
): T[] {
  return assistants
    .map((assistant) => ({ assistant, score: lexicalScore(query, assistant) }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.assistant.name.localeCompare(b.assistant.name, 'fr'))
    .map((item) => item.assistant)
}

// Une requête au serveur n'est faite que si elle apporte quelque chose : assez de caractères, et assez d'assistants.
export function needsServerSearch(query: string, assistantCount: number): boolean {
  return query.trim().length >= MIN_QUERY_LENGTH && assistantCount >= SERVER_SEARCH_FROM
}
