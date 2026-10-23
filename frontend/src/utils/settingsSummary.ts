// Les réglages dits en une phrase, en langage simple : la ligne sous le titre d'une section repliée, et le
// récapitulatif de l'assistant de création.
import type { SettingsDraft, StepKey } from './settingsDraft.ts'

const STRATEGY_LABEL = {
  llm: 'Par le modèle, qui coupe là où le sens change',
  paragraph: 'Par paragraphe',
  fixed: 'Par blocs de taille fixe',
  semantic: 'Par regroupement de phrases de même sens',
} as const

export function chunkingSummary(draft: SettingsDraft): string {
  const { strategy, chunkSize } = draft.chunking
  const size = strategy === 'fixed' && chunkSize !== '' ? ` (${chunkSize} tokens)` : ''
  return `${STRATEGY_LABEL[strategy]}${size}`
}

// Le modèle choisi pour l'étape, et si des consignes sont données.
export function stepSummary(draft: SettingsDraft, step: StepKey): string {
  const model = draft.models[step] || 'modèle par défaut'
  return draft.instructions[step].trim() ? `${model} · consignes personnalisées` : model
}

export function summaryReadingSummary(draft: SettingsDraft): string {
  const long = draft.longDocs
  if (long.summaryMode === 'percent') {
    return long.separateEnds
      ? `début ${long.summaryHeadPercent || 0} % et fin ${long.summaryTailPercent || 0} %`
      : `${long.summaryPercent} % (moitié au début, moitié à la fin)`
  }
  if (long.summaryMode === 'pages') return `pages ${long.summaryPageRanges.trim() || '…'}`
  return 'tout le document'
}

export function isEverythingRead(draft: SettingsDraft): boolean {
  const long = draft.longDocs
  return (
    long.summaryMode === 'all' &&
    long.qaMaxQuestions === '' &&
    long.extractionPercent === 100 &&
    long.extractionMaxWindows === ''
  )
}

// Ce que les longs documents ne lisent qu'en partie, ou « tout est lu ».
export function longDocsSummary(draft: SettingsDraft): string {
  if (isEverythingRead(draft)) return 'Tout est lu, quelle que soit la longueur du document'
  const long = draft.longDocs
  const parts: string[] = []
  if (long.summaryMode !== 'all') parts.push(`résumé : ${summaryReadingSummary(draft)}`)
  if (long.qaMaxQuestions !== '') parts.push(`${long.qaMaxQuestions} questions au plus`)
  if (long.extractionPercent !== 100 || long.extractionMaxWindows !== '') {
    const cap = long.extractionMaxWindows !== '' ? `, ${long.extractionMaxWindows} fenêtres au plus` : ''
    parts.push(`entités : ${long.extractionPercent} % des pages${cap}`)
  }
  return `Au-delà de ${long.samplingMinPages} pages : ${parts.join(' · ')}`
}
