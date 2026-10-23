// Réglages des longs documents (#372) : ce que le résumé, les questions et les entités lisent d'un document qui
// dépasse un certain nombre de pages. La validation reprend celle du backend (la sienne fait foi : elle refuse ce que
// celle-ci laisserait passer) pour signaler l'erreur à côté du champ, avant l'envoi.

export type SummaryMode = 'all' | 'percent' | 'pages'

// Un champ numérique vidé vaut '' : le v-model.number d'un <input> le donne tel quel.
export type NumberField = number | ''

export interface LongDocumentsDraft {
  samplingMinPages: NumberField
  summaryMode: SummaryMode
  summaryPercent: NumberField
  // Début et fin réglés séparément, au lieu d'un pourcentage réparti moitié-moitié.
  separateEnds: boolean
  summaryHeadPercent: NumberField
  summaryTailPercent: NumberField
  summaryPageRanges: string
  // Vide : pas de plafond.
  qaMaxQuestions: NumberField
  extractionPercent: NumberField
  extractionMaxWindows: NumberField
}

export type LongDocumentsField = Exclude<keyof LongDocumentsDraft, 'summaryMode' | 'separateEnds'>
export type LongDocumentsErrors = Partial<Record<LongDocumentsField, string>>

// Ce que le backend reçoit (les clés de pipeline_windows) ; null retire un plafond ou le début/fin séparés.
export interface LongDocumentsPayload {
  sampling_min_pages: number
  summary_mode: SummaryMode
  summary_percent: number
  summary_head_percent: number | null
  summary_tail_percent: number | null
  summary_page_ranges: string
  qa_max_questions: number | null
  extraction_percent: number
  extraction_max_windows: number | null
}

export interface LongDocumentsSettings {
  samplingMinPages: number
  summaryMode: SummaryMode
  summaryPercent: number
  summaryHeadPercent: number | null
  summaryTailPercent: number | null
  summaryPageRanges: string
  qaMaxQuestions: number | null
  extractionPercent: number
  extractionMaxWindows: number | null
}

export type PageRange = { first: number; last: number | null }
export type PageRangesResult = { ok: true; ranges: PageRange[] } | { ok: false; error: string }

const RANGE = /^(\d+)(?:(-)(\d*))?$/

// « 1-5, 40-45, 90- » : une page, des pages a à b, ou à partir de la page a jusqu'à la fin.
export function parsePageRanges(text: string): PageRangesResult {
  const ranges: PageRange[] = []
  for (const raw of text.split(',')) {
    const part = raw.trim()
    if (!part) continue
    const found = RANGE.exec(part.replace(/\s*-\s*/g, '-'))
    if (!found) return { ok: false, error: `« ${part} » n'est ni une page ni une plage de pages.` }
    const first = Number(found[1])
    const last = found[2] ? (found[3] ? Number(found[3]) : null) : first
    if (first < 1 || (last !== null && last < first)) {
      return { ok: false, error: `« ${part} » n'est pas une plage de pages valide.` }
    }
    ranges.push({ first, last })
  }
  return { ok: true, ranges }
}

export function draftFromSettings(settings: LongDocumentsSettings): LongDocumentsDraft {
  return {
    samplingMinPages: settings.samplingMinPages,
    summaryMode: settings.summaryMode,
    summaryPercent: settings.summaryPercent,
    separateEnds: settings.summaryHeadPercent !== null || settings.summaryTailPercent !== null,
    summaryHeadPercent: settings.summaryHeadPercent ?? '',
    summaryTailPercent: settings.summaryTailPercent ?? '',
    summaryPageRanges: settings.summaryPageRanges,
    qaMaxQuestions: settings.qaMaxQuestions ?? '',
    extractionPercent: settings.extractionPercent,
    extractionMaxWindows: settings.extractionMaxWindows ?? '',
  }
}

const asNumber = (value: NumberField): number | null => (value === '' ? null : value)

// Le pourcentage symétrique, réparti moitié au début, moitié à la fin (le début prend l'éventuelle page de plus,
// comme le worker).
export function splitPercent(percent: NumberField): [number, number] {
  const total = Math.min(Math.max(Math.trunc(asNumber(percent) ?? 0), 0), 100)
  const head = Math.ceil(total / 2)
  return [head, total - head]
}

// L'inverse, en repassant à un pourcentage unique : ce qui était lu au début et à la fin ensemble.
export function joinPercent(head: NumberField, tail: NumberField): number {
  const total = Math.trunc((asNumber(head) ?? 0) + (asNumber(tail) ?? 0))
  return Math.min(Math.max(total, 1), 100)
}

// Passe du pourcentage unique au début et fin séparés, ou l'inverse, sans perdre ce qui était réglé.
export function setSeparateEnds(draft: LongDocumentsDraft, separate: boolean): void {
  if (separate === draft.separateEnds) return
  if (separate) {
    ;[draft.summaryHeadPercent, draft.summaryTailPercent] = splitPercent(draft.summaryPercent)
  } else {
    draft.summaryPercent = joinPercent(draft.summaryHeadPercent, draft.summaryTailPercent)
  }
  draft.separateEnds = separate
}

function integerIn(value: NumberField, min: number, max: number | null, label: string): string | undefined {
  if (value === '' || !Number.isInteger(value)) return `${label} : saisir un nombre entier.`
  if (value < min || (max !== null && value > max)) {
    return max === null ? `${label} : au moins ${min}.` : `${label} : entre ${min} et ${max}.`
  }
  return undefined
}

function optionalInteger(value: NumberField, label: string): string | undefined {
  return value === '' ? undefined : integerIn(value, 1, null, label)
}

export function validateLongDocuments(draft: LongDocumentsDraft): LongDocumentsErrors {
  const errors: LongDocumentsErrors = {}
  const set = (field: LongDocumentsField, message: string | undefined) => {
    if (message) errors[field] = message
  }
  set('samplingMinPages', integerIn(draft.samplingMinPages, 1, null, 'Seuil'))
  if (draft.summaryMode === 'percent') {
    if (draft.separateEnds) {
      set('summaryHeadPercent', integerIn(draft.summaryHeadPercent, 0, 100, 'Début'))
      set('summaryTailPercent', integerIn(draft.summaryTailPercent, 0, 100, 'Fin'))
      if (!errors.summaryHeadPercent && !errors.summaryTailPercent) {
        const total = (draft.summaryHeadPercent as number) + (draft.summaryTailPercent as number)
        if (total < 1 || total > 100) {
          set('summaryTailPercent', `Début et fin ensemble : entre 1 et 100 % (là, ${total} %).`)
        }
      }
    } else {
      set('summaryPercent', integerIn(draft.summaryPercent, 1, 100, 'Part du document résumée'))
    }
  }
  // Les plages sont enregistrées quel que soit le mode : le backend les refuse mal formées même hors du mode « pages ».
  if (draft.summaryMode === 'pages' || draft.summaryPageRanges.trim()) {
    const parsed = parsePageRanges(draft.summaryPageRanges)
    if (!parsed.ok) set('summaryPageRanges', parsed.error)
    else if (!parsed.ranges.length) set('summaryPageRanges', 'Indiquer au moins une page ou une plage de pages.')
  }
  set('qaMaxQuestions', optionalInteger(draft.qaMaxQuestions, 'Nombre maximum de questions'))
  set('extractionPercent', integerIn(draft.extractionPercent, 1, 100, 'Part du document analysée'))
  set('extractionMaxWindows', optionalInteger(draft.extractionMaxWindows, 'Nombre maximum de fenêtres'))
  return errors
}

// Valable seulement quand le brouillon est valide (voir validateLongDocuments).
export function toPayload(draft: LongDocumentsDraft): LongDocumentsPayload {
  const separate = draft.summaryMode === 'percent' && draft.separateEnds
  return {
    sampling_min_pages: draft.samplingMinPages as number,
    summary_mode: draft.summaryMode,
    summary_percent: draft.summaryPercent === '' ? 30 : draft.summaryPercent,
    summary_head_percent: separate ? asNumber(draft.summaryHeadPercent) : null,
    summary_tail_percent: separate ? asNumber(draft.summaryTailPercent) : null,
    summary_page_ranges: draft.summaryPageRanges.trim(),
    qa_max_questions: asNumber(draft.qaMaxQuestions),
    extraction_percent: draft.extractionPercent as number,
    extraction_max_windows: asNumber(draft.extractionMaxWindows),
  }
}

// Les mêmes réglages que par défaut : tout est lu, rien n'est plafonné. Sert de référence à « au lieu de M appels ».
export const READ_EVERYTHING: Pick<
  LongDocumentsPayload,
  'summary_mode' | 'qa_max_questions' | 'extraction_percent' | 'extraction_max_windows'
> = {
  summary_mode: 'all',
  qa_max_questions: null,
  extraction_percent: 100,
  extraction_max_windows: null,
}

// « 1-30, 271-300 » à partir des plages [[1, 30], [271, 300]] d'un résumé partiel.
export function formatPages(ranges: number[][]): string {
  return ranges.map(([first, last]) => (first === last ? `${first}` : `${first}-${last}`)).join(', ')
}
