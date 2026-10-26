// The evaluation metrics the UI knows how to label, keyed by their namedScores name -
// what the worker's promptfoo assertions write (worker/evaluation/app/promptfoo/
// create_tests.py) and what the backend serves through, keyed as-is. The backend is
// generic: it serves whatever the run's artifact holds, so a metric missing from this
// registry still renders, under its raw key - an entry only adds the French label,
// the tooltip and a stable display order.

export interface EvaluationMetricInfo {
  label: string
  tooltip: string
}

export const EVALUATION_METRICS: Record<string, EvaluationMetricInfo> = {
  factuality: {
    label: 'Factualité',
    tooltip:
      'Score moyen donné par le juge à la factualité des réponses générées (1.0 = toujours fidèles à la réponse attendue).',
  },
  context_faithfulness: {
    label: 'Fidélité au contexte',
    tooltip:
      "Score moyen donné par le juge à l'ancrage des réponses générées dans le contexte réellement récupéré (1.0 = rien d'inventé hors des extraits). « — » sur les évaluations antérieures à la métrique.",
  },
}

// Known metrics first, in this order; unknown ones after, alphabetically - the cards,
// the per-pair lines and the dashboard columns stay stable as metrics appear.
export const EVALUATION_METRIC_ORDER = ['factuality', 'context_faithfulness']

export function metricLabel(key: string): string {
  return EVALUATION_METRICS[key]?.label ?? key
}

export function metricTooltip(key: string): string | undefined {
  return EVALUATION_METRICS[key]?.tooltip
}

export function orderedMetricKeys(keys: Iterable<string>): string[] {
  const listed = [...keys]
  const known = EVALUATION_METRIC_ORDER.filter((key) => listed.includes(key))
  const unknown = listed.filter((key) => !EVALUATION_METRIC_ORDER.includes(key)).sort()
  return [...known, ...unknown]
}
