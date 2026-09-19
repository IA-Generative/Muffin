// The registry this dashboard renders from (see QualityDashboardView.vue) - adding a metric
// later (a 5th family, or a new metric inside an existing one) means adding an entry here, never
// touching the view's template/logic.
//
// Not connected to the backend yet (see #33): every metric's value is a deterministic mock,
// seeded from the selected collection's id so switching collections visibly changes the numbers
// without pretending to be real data. Each family maps to the issue that will eventually compute
// and persist it for real - #11 (retrieval), #30 (feedback), #31 (discussion), #32
// (groundedness, already implemented backend-side, not wired here yet either).

export type MetricFamily = 'retrieval' | 'feedback' | 'discussion' | 'groundedness'

export interface MetricFamilyInfo {
  id: MetricFamily
  label: string
  description: string
  issue: string
}

export interface MetricDefinition {
  id: string
  family: MetricFamily
  label: string
  // Plain-language explanation, not just a name - what the issue calls "une explication
  // compréhensible pour un non-spécialiste".
  description: string
  format: (value: number) => string
  // A stand-in for the real per-collection value #11/#30/#31/#32 will eventually provide.
  mockValue: (seed: number) => number
}

export const METRIC_FAMILIES: MetricFamilyInfo[] = [
  {
    id: 'retrieval',
    label: 'Retrieval',
    description:
      "Est-ce que la recherche documentaire retrouve les bons passages ? Mesuré en rejouant les paires question/réponse validées de la collection contre son index actuel.",
    issue: '#11',
  },
  {
    id: 'feedback',
    label: 'Retours utilisateur',
    description:
      "Ce que les utilisateurs pensent réellement des réponses reçues - pouce haut/bas et raisons données sur chaque réponse.",
    issue: '#30',
  },
  {
    id: 'discussion',
    label: 'Score de discussion',
    description:
      "Cohérence d'une conversation dans son ensemble : pas de contradiction d'un tour à l'autre, bonne exploitation du contexte déjà échangé.",
    issue: '#31',
  },
  {
    id: 'groundedness',
    label: 'Groundedness',
    description:
      "Proportion des réponses dont chaque affirmation est réellement supportée par une source citée, pas juste plausible.",
    issue: '#32',
  },
]

function pct(value: number): string {
  return `${Math.round(value * 100)} %`
}

function ratio(value: number): string {
  return value.toFixed(2)
}

// Small deterministic PRNG (mulberry32) seeded from the collection id, so the same collection
// always shows the same mock numbers instead of flickering on every render.
function seededRandom(seed: number): () => number {
  let a = seed || 1
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function seedFromId(id: string): number {
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) | 0
  return hash
}

function between(seed: number, min: number, max: number, offset = 0): number {
  const rand = seededRandom(seed + offset)()
  return min + rand * (max - min)
}

export const METRICS: MetricDefinition[] = [
  {
    id: 'precisionAtK',
    family: 'retrieval',
    label: 'Precision@k',
    description: 'Parmi les passages retrouvés pour une question, quelle proportion est réellement pertinente.',
    format: pct,
    mockValue: (seed) => between(seed, 0.55, 0.92, 1),
  },
  {
    id: 'recallAtK',
    family: 'retrieval',
    label: 'Recall@k',
    description: 'Parmi les passages réellement pertinents, quelle proportion a été retrouvée.',
    format: pct,
    mockValue: (seed) => between(seed, 0.5, 0.88, 2),
  },
  {
    id: 'mrr',
    family: 'retrieval',
    label: 'MRR',
    description: "Mean Reciprocal Rank - en moyenne, à quel rang apparaît le premier passage pertinent (1.0 = toujours en premier).",
    format: ratio,
    mockValue: (seed) => between(seed, 0.4, 0.95, 3),
  },
  {
    id: 'ndcg',
    family: 'retrieval',
    label: 'nDCG',
    description: "Normalized Discounted Cumulative Gain - récompense un bon classement, pas juste la présence du bon passage quelque part dans les résultats.",
    format: ratio,
    mockValue: (seed) => between(seed, 0.45, 0.9, 4),
  },
  {
    id: 'upRatio',
    family: 'feedback',
    label: 'Réponses appréciées',
    description: 'Proportion des retours utilisateur qui sont un pouce haut plutôt qu\'un pouce bas.',
    format: pct,
    mockValue: (seed) => between(seed, 0.6, 0.95, 5),
  },
  {
    id: 'topReason',
    family: 'feedback',
    label: 'Principale raison de pouce bas',
    description: 'La raison la plus souvent sélectionnée parmi les retours négatifs (échelle 0-1 = part de ce motif).',
    format: pct,
    mockValue: (seed) => between(seed, 0.2, 0.6, 6),
  },
  {
    id: 'coherence',
    family: 'discussion',
    label: 'Cohérence',
    description: "Sur les conversations à plusieurs tours, proportion sans contradiction détectée d'une réponse à l'autre.",
    format: pct,
    mockValue: (seed) => between(seed, 0.7, 0.97, 7),
  },
  {
    id: 'contextUse',
    family: 'discussion',
    label: 'Exploitation du contexte',
    description: "Proportion des questions de suivi ('et pour...', 'et elle ?') correctement rattachées à ce qui précède.",
    format: pct,
    mockValue: (seed) => between(seed, 0.65, 0.93, 8),
  },
  {
    id: 'groundedRatio',
    family: 'groundedness',
    label: 'Réponses entièrement groundées',
    description: "Proportion des réponses dont chaque affirmation est supportée par une source citée, sans relance nécessaire.",
    format: pct,
    mockValue: (seed) => between(seed, 0.65, 0.96, 9),
  },
  {
    id: 'avgRetries',
    family: 'groundedness',
    label: 'Relances moyennes',
    description: "Nombre moyen de recherches ciblées supplémentaires déclenchées avant qu'une réponse soit jugée groundée.",
    format: ratio,
    mockValue: (seed) => between(seed, 0, 1.5, 10),
  },
]
