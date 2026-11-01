import type { Share, SharePermission, ShareSubjectType } from './collection'

export type AssistantVisibility = 'private' | 'public'
// Ce qu'un assistant peut consulter d'autre (#531) : rien (par défaut), tout ce que la personne peut lire, ou une liste.
export type ConsultMode = 'none' | 'all' | 'list'

// Les outils facultatifs de l'agent qu'un assistant peut couper. Le graphe de l'agent est le même pour tous : un assistant
// n'en change que les consignes, les collections et ces outils. `search` n'en fait pas partie : une réponse en est faite.
export const OPTIONAL_TOOLS = [
  { id: 'tabular_query', label: 'Calculs sur les tableaux', hint: 'moyennes, totaux, tris sur des CSV / Excel' },
  { id: 'page_content', label: 'Texte et image d’une page', hint: 'afficher une page précise d’un document' },
  { id: 'list_documents', label: 'Liste et résumé des documents', hint: 'combien de documents, résumé d’un document' },
  { id: 'list_collections', label: 'Liste des collections', hint: 'quelles collections existent' },
  { id: 'collection_summary', label: 'Résumé d’une collection', hint: 'de quoi parle une collection' },
  { id: 'time', label: 'Date et périodes', hint: 'aujourd’hui, ce mois-ci, la semaine dernière' },
] as const

export interface Assistant {
  id: string
  name: string
  description: string
  icon: string
  color: string
  // Null pour qui ne fait que lire un assistant dont l'auteur masque les consignes : elles s'appliquent quand même.
  instructions: string | null
  instructionsHidden: boolean
  hideInstructions: boolean
  // Seulement celles que vous pouvez lire ; les autres ne sont que comptées, jamais nommées.
  collections: { id: string; name: string }[]
  inaccessibleCollectionCount: number
  includeDescendants: boolean
  webSearchAllowed: boolean
  disabledTools: string[]
  consultMode: ConsultMode
  // Ceux que vous pouvez lire, nommés ; les autres ne sont que comptés.
  consulted: { id: string; name: string }[]
  inaccessibleConsultedCount: number
  suggestions: string[]
  visibility: AssistantVisibility
  version: number
  isOwner: boolean
  canEdit: boolean
  shareCount: number
  updatedAt: string
}

export interface AssistantDraft {
  name: string
  description: string
  icon: string
  instructions: string
  hideInstructions: boolean
  collectionIds: string[]
  includeDescendants: boolean
  webSearchAllowed: boolean
  disabledTools: string[]
  consultMode: ConsultMode
  consultAssistantIds: string[]
  // Une question par ligne.
  suggestions: string
}

export type AssistantShare = Share
export type { SharePermission, ShareSubjectType }
