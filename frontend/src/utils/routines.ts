import type { RoutineDraft, RoutineRunStatus, RoutineSchedule, RoutineState } from '../types/routine'

export const WEEKDAYS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']

export const DEFAULT_TIMEZONE = 'Europe/Paris'

// Le fuseau du navigateur quand il est connu, sinon celui de l'application : l'heure « 9 h » est celle de la personne.
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_TIMEZONE
  } catch {
    return DEFAULT_TIMEZONE
  }
}

export function emptySchedule(): RoutineSchedule {
  return {
    kind: 'weekly',
    timezone: browserTimezone(),
    intervalMinutes: null,
    timeOfDay: '09:00',
    weekdays: [0],
    dayOfMonth: null,
  }
}

export function emptyDraft(): RoutineDraft {
  return {
    name: '',
    question: '',
    collectionIds: [],
    includeDescendants: true,
    assistantId: null,
    webSearch: false,
    schedule: emptySchedule(),
    condition: 'always',
    resultMode: 'new_conversation',
    notify: 'always',
  }
}

// « 09:00:00 » (ce que renvoie le serveur) → « 09:00 » (ce que sait lire un champ d'heure).
export function shortTime(value: string | null): string {
  return value ? value.slice(0, 5) : ''
}

function everyHours(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? 'Tous les jours' : `Tous les ${minutes / 1440} jours`
  if (minutes % 60 === 0) return minutes === 60 ? 'Toutes les heures' : `Toutes les ${minutes / 60} heures`
  return `Toutes les ${minutes} minutes`
}

function days(weekdays: number[]): string {
  const names = [...weekdays].sort((a, b) => a - b).map((day) => WEEKDAYS[day])
  if (names.length === 1) return `Le ${names[0]}`
  return `Le ${names.slice(0, -1).join(', ')} et le ${names[names.length - 1]}`
}

// Le rythme en une phrase, comme la personne le dirait.
export function describeSchedule(schedule: RoutineSchedule): string {
  const at = shortTime(schedule.timeOfDay).replace(':', ' h ')
  if (schedule.kind === 'interval') return everyHours(schedule.intervalMinutes ?? 0)
  if (schedule.kind === 'daily') return `Tous les jours à ${at}`
  if (schedule.kind === 'weekly') return `${days(schedule.weekdays ?? [])} à ${at}`
  const day = schedule.dayOfMonth ?? 1
  return `${day === 1 ? 'Le 1er' : `Le ${day}`} de chaque mois à ${at}`
}

const SKIP_REASONS: Record<string, string> = {
  no_new_documents: 'Aucun nouveau document',
  previous_running: 'La précédente était encore en cours',
  access_lost: 'Accès perdu aux collections',
  daily_limit: 'Limite d’exécutions du jour atteinte',
  busy: 'Trop d’exécutions en même temps',
  function_off: 'Fonction désactivée',
}

export function skipReasonLabel(reason: string | null): string {
  return (reason && SKIP_REASONS[reason]) || 'Sautée'
}

export function runStatusLabel(status: RoutineRunStatus, reason: string | null = null): string {
  if (status === 'skipped') return skipReasonLabel(reason)
  return { running: 'En cours', succeeded: 'Réussie', failed: 'Échouée' }[status]
}

const SUSPENSIONS: Record<string, string> = {
  failures: 'après des échecs répétés',
  inactive: 'parce que vous ne vous êtes pas connecté depuis longtemps',
  admin: 'par un administrateur',
}

export function stateLabel(state: RoutineState, reason: string | null = null): string {
  if (state === 'active') return 'Active'
  if (state === 'paused') return 'En pause'
  return `Suspendue${reason && SUSPENSIONS[reason] ? ` ${SUSPENSIONS[reason]}` : ''}`
}

export function formatDateTime(value: string | null, timezone?: string): string {
  if (!value) return '—'
  try {
    return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short', timeZone: timezone }).format(
      new Date(value),
    )
  } catch {
    return new Date(value).toLocaleString('fr-FR')
  }
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return ''
  if (seconds < 60) return `${seconds} s`
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`
}

// Ce que le formulaire peut déjà dire sans interroger le serveur ; le serveur reste juge.
export function scheduleProblem(schedule: RoutineSchedule, minIntervalMinutes: number): string | null {
  if (schedule.kind === 'interval') {
    if (!schedule.intervalMinutes) return 'Indiquez l’intervalle.'
    if (schedule.intervalMinutes < minIntervalMinutes) {
      return `L’intervalle minimal est de ${minIntervalMinutes} minutes.`
    }
    return null
  }
  if (!schedule.timeOfDay) return 'Indiquez l’heure.'
  if (schedule.kind === 'weekly' && !schedule.weekdays?.length) return 'Choisissez au moins un jour.'
  if (schedule.kind === 'monthly' && !schedule.dayOfMonth) return 'Indiquez le jour du mois.'
  return null
}
