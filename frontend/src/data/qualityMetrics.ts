// The registry this dashboard renders from (see QualityDashboardView.vue) - adding a metric
// later (a 5th family, or a new metric inside an existing one) means adding an entry here, never
// touching the view's template/logic.
//
// Not connected to the backend yet (see #33): every metric's value (and sample size) is a
// deterministic mock, seeded from the selected collection's id so switching collections visibly
// changes the numbers without pretending to be real data. Each family maps to the issue that
// will eventually compute and persist it for real - #11 (retrieval), #30 (feedback), #31
// (discussion), #32 (groundedness, already implemented backend-side, not wired here yet
// either). "cost" has no tracking issue yet - nothing in the backend computes this today.

export type MetricFamily = 'retrieval' | 'feedback' | 'discussion' | 'groundedness' | 'cost'

export interface MetricFamilyInfo {
  id: MetricFamily
  label: string
  description: string
  // Absent for a family with no tracking issue yet (cost/latency - nothing in the backend
  // computes or persists this today, this card is purely illustrative until one exists).
  issue?: string
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
  // How many underlying data points (evaluated QA pairs, feedbacks, runs...) this number is
  // computed from - shown as "n = XX" so a ratio is never read as more confident than it
  // actually is (a precision@k of 81% means something very different on 4 QA pairs vs 400).
  mockSampleSize: (seed: number) => number
}

export interface MockEvaluationRun {
  id: string
  label: string
}

// Retrieval is the one family with a real notion of a versioned "evaluation run" (see #11's
// EvaluationRun model, already shown per-collection in CollectionEvaluationTab.vue) - a snapshot
// of a specific chunking/embedding config replayed against the collection's QA pairs. The other
// families are continuous signals over live usage, not discrete runs, so this picker only scopes
// retrieval metrics.
export const MOCK_EVALUATION_RUNS: MockEvaluationRun[] = [
  { id: 'eval-run-0', label: 'Il y a 2 jours' },
  { id: 'eval-run-1', label: 'Il y a 9 jours' },
  { id: 'eval-run-2', label: 'Il y a 1 mois' },
]

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
  {
    id: 'cost',
    label: 'Coût & latence',
    description:
      "Combien coûte et combien de temps prend une réponse de l'agent - pas une mesure de qualité perçue, mais ce qui détermine si le produit reste utilisable et soutenable à l'échelle.",
    // No tracking issue yet - nothing in the backend computes or persists this today.
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

function sampleCount(seed: number, min: number, max: number, offset: number): number {
  return Math.round(between(seed, min, max, offset))
}

export const METRICS: MetricDefinition[] = [
  {
    id: 'precisionAtK',
    family: 'retrieval',
    label: 'Precision@k',
    description: 'Parmi les passages retrouvés pour une question, quelle proportion est réellement pertinente.',
    format: pct,
    mockValue: (seed) => between(seed, 0.55, 0.92, 1),
    mockSampleSize: (seed) => sampleCount(seed, 8, 80, 101),
  },
  {
    id: 'recallAtK',
    family: 'retrieval',
    label: 'Recall@k',
    description: 'Parmi les passages réellement pertinents, quelle proportion a été retrouvée.',
    format: pct,
    mockValue: (seed) => between(seed, 0.5, 0.88, 2),
    mockSampleSize: (seed) => sampleCount(seed, 8, 80, 101),
  },
  {
    id: 'mrr',
    family: 'retrieval',
    label: 'MRR',
    description:
      "Mean Reciprocal Rank - en moyenne, à quel rang apparaît le premier passage pertinent (1.0 = toujours en premier).",
    format: ratio,
    mockValue: (seed) => between(seed, 0.4, 0.95, 3),
    mockSampleSize: (seed) => sampleCount(seed, 8, 80, 101),
  },
  {
    id: 'ndcg',
    family: 'retrieval',
    label: 'nDCG',
    description:
      "Normalized Discounted Cumulative Gain - récompense un bon classement, pas juste la présence du bon passage quelque part dans les résultats.",
    format: ratio,
    mockValue: (seed) => between(seed, 0.45, 0.9, 4),
    mockSampleSize: (seed) => sampleCount(seed, 8, 80, 101),
  },
  {
    id: 'upRatio',
    family: 'feedback',
    label: 'Réponses appréciées',
    description: "Proportion des retours utilisateur qui sont un pouce haut plutôt qu'un pouce bas.",
    format: pct,
    mockValue: (seed) => between(seed, 0.6, 0.95, 5),
    mockSampleSize: (seed) => sampleCount(seed, 15, 400, 15),
  },
  {
    id: 'topReason',
    family: 'feedback',
    label: 'Principale raison de pouce bas',
    description: 'La raison la plus souvent sélectionnée parmi les retours négatifs (échelle 0-1 = part de ce motif).',
    format: pct,
    mockValue: (seed) => between(seed, 0.2, 0.6, 6),
    mockSampleSize: (seed) => sampleCount(seed, 5, 120, 16),
  },
  {
    id: 'coherence',
    family: 'discussion',
    label: 'Cohérence',
    description: "Sur les conversations à plusieurs tours, proportion sans contradiction détectée d'une réponse à l'autre.",
    format: pct,
    mockValue: (seed) => between(seed, 0.7, 0.97, 7),
    mockSampleSize: (seed) => sampleCount(seed, 10, 150, 17),
  },
  {
    id: 'contextUse',
    family: 'discussion',
    label: 'Exploitation du contexte',
    description: "Proportion des questions de suivi ('et pour...', 'et elle ?') correctement rattachées à ce qui précède.",
    format: pct,
    mockValue: (seed) => between(seed, 0.65, 0.93, 8),
    mockSampleSize: (seed) => sampleCount(seed, 10, 150, 17),
  },
  {
    id: 'avgTurns',
    family: 'discussion',
    label: 'Longueur moyenne d\'une discussion',
    description:
      "Nombre moyen d'échanges (question + réponse) par conversation - une discussion très courte n'a souvent pas eu l'occasion de dériver ou de mal réutiliser le contexte, une très longue mérite un regard plus attentif sur la cohérence.",
    format: (value) => `${value.toFixed(1)} échanges`,
    mockValue: (seed) => between(seed, 1.5, 6, 18),
    mockSampleSize: (seed) => sampleCount(seed, 10, 150, 17),
  },
  {
    id: 'groundedRatio',
    family: 'groundedness',
    label: 'Réponses entièrement groundées',
    description: "Proportion des réponses dont chaque affirmation est supportée par une source citée, sans relance nécessaire.",
    format: pct,
    mockValue: (seed) => between(seed, 0.65, 0.96, 9),
    mockSampleSize: (seed) => sampleCount(seed, 20, 400, 19),
  },
  {
    id: 'avgRetries',
    family: 'groundedness',
    label: 'Relances moyennes',
    description: "Nombre moyen de recherches ciblées supplémentaires déclenchées avant qu'une réponse soit jugée groundée.",
    format: ratio,
    mockValue: (seed) => between(seed, 0, 1.5, 10),
    mockSampleSize: (seed) => sampleCount(seed, 20, 400, 19),
  },
  {
    id: 'avgLatency',
    family: 'cost',
    label: 'Latence moyenne',
    description: "Temps moyen entre la question posée et la réponse complète, recherche et vérifications comprises.",
    format: (value) => `${value.toFixed(1)} s`,
    mockValue: (seed) => between(seed, 3, 14, 20),
    mockSampleSize: (seed) => sampleCount(seed, 30, 500, 21),
  },
  {
    id: 'avgCost',
    family: 'cost',
    label: 'Coût moyen par réponse',
    description:
      "Coût LLM estimé (recherche, génération, vérifications) pour produire une réponse, au tarif du modèle utilisé.",
    format: (value) => `${value.toFixed(3)} €`,
    mockValue: (seed) => between(seed, 0.002, 0.08, 22),
    mockSampleSize: (seed) => sampleCount(seed, 30, 500, 21),
  },
]
