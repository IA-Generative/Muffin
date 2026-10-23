// Les profils proposés à la création d'une collection : un choix en langage simple (rapide, équilibré, précis) qui
// remplit les réglages techniques - le découpage et ce que les longs documents lisent (#372). Les modèles ne sont pas
// touchés : ils dépendent de ce que le serveur offre, pas du besoin.
import type { SettingsDraft } from './settingsDraft.ts'
import type { LongDocumentsDraft } from './longDocuments.ts'

export type ProfileId = 'fast' | 'balanced' | 'precise'

export interface Profile {
  id: ProfileId
  label: string
  tagline: string
  // Ce que le profil règle, en une phrase chacun.
  details: string[]
  // Ce qu'il fait perdre.
  tradeOff: string
  recommended?: boolean
  chunkingStrategy: SettingsDraft['chunking']['strategy']
  longDocs: Pick<
    LongDocumentsDraft,
    'summaryMode' | 'summaryPercent' | 'qaMaxQuestions' | 'extractionPercent' | 'extractionMaxWindows'
  >
}

const EVERYTHING: Profile['longDocs'] = {
  summaryMode: 'all',
  summaryPercent: 30,
  qaMaxQuestions: '',
  extractionPercent: 100,
  extractionMaxWindows: '',
}

export const PROFILES: Profile[] = [
  {
    id: 'fast',
    label: 'Rapide et économique',
    tagline: 'Pour de gros volumes, ou pour essayer.',
    details: [
      'Découpage par paragraphe, sans appel au modèle.',
      'Pour un document de plus de 100 pages : un résumé de 30 % (début et fin), 100 questions au plus, 20 % des pages analysées pour les entités.',
    ],
    tradeOff: 'Les longs documents sont résumés et analysés en partie seulement.',
    chunkingStrategy: 'paragraph',
    longDocs: { ...EVERYTHING, summaryMode: 'percent', summaryPercent: 30, qaMaxQuestions: 100, extractionPercent: 20 },
  },
  {
    id: 'balanced',
    label: 'Équilibré',
    tagline: 'Le bon compromis pour la plupart des collections.',
    details: [
      'Découpage par le modèle, qui coupe là où le sens change.',
      'Pour un document de plus de 100 pages : un résumé de 50 % (début et fin), 300 questions au plus, 50 % des pages analysées pour les entités.',
    ],
    tradeOff: 'Les très longs documents sont résumés et analysés à moitié.',
    recommended: true,
    chunkingStrategy: 'llm',
    longDocs: { ...EVERYTHING, summaryMode: 'percent', summaryPercent: 50, qaMaxQuestions: 300, extractionPercent: 50 },
  },
  {
    id: 'precise',
    label: 'Précis',
    tagline: 'Pour des documents où chaque page compte.',
    details: [
      'Découpage par le modèle, qui coupe là où le sens change.',
      'Tout le document est lu pour le résumé, les questions et les entités, quelle que soit sa longueur.',
    ],
    tradeOff: 'Plus d’appels au modèle, donc plus lent et plus coûteux sur les longs documents.',
    chunkingStrategy: 'llm',
    longDocs: EVERYTHING,
  },
]

export function profileById(id: ProfileId): Profile {
  return PROFILES.find((profile) => profile.id === id) as Profile
}

// Applique un profil au brouillon : ce qu'il règle est remplacé, le reste (modèles, consignes, taille des chunks,
// seuil) est gardé. Le début et la fin sont répartis moitié-moitié, pas séparés.
export function applyProfile(draft: SettingsDraft, profile: Profile): void {
  draft.chunking.strategy = profile.chunkingStrategy
  Object.assign(draft.longDocs, profile.longDocs, {
    separateEnds: false,
    summaryHeadPercent: '',
    summaryTailPercent: '',
  })
}

// Le profil que les réglages actuels réalisent exactement, ou null (« personnalisé »).
export function detectProfile(draft: SettingsDraft): ProfileId | null {
  const long = draft.longDocs
  const found = PROFILES.find(
    (profile) =>
      profile.chunkingStrategy === draft.chunking.strategy &&
      !long.separateEnds &&
      long.summaryMode === profile.longDocs.summaryMode &&
      (profile.longDocs.summaryMode !== 'percent' || long.summaryPercent === profile.longDocs.summaryPercent) &&
      long.qaMaxQuestions === profile.longDocs.qaMaxQuestions &&
      long.extractionPercent === profile.longDocs.extractionPercent &&
      long.extractionMaxWindows === profile.longDocs.extractionMaxWindows,
  )
  return found?.id ?? null
}
