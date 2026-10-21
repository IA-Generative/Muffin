// When a URL document's page is fetched again (#19) - the backend's RefreshSchedule. Every time is on
// the hour or at half past: the backend scans for documents due at those times only.
export type RefreshKind = 'once' | 'daily' | 'weekly' | 'interval'

export interface RefreshSchedule {
  kind: RefreshKind
  run_at?: string | null
  time_of_day?: string | null
  weekdays?: number[] | null
  interval_minutes?: number | null
  timezone?: string
}

// 0 = Monday, as Python's weekday().
export const WEEKDAYS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

// 00:00, 00:30 ... 23:30.
export const HALF_HOURS = Array.from(
  { length: 48 },
  (_, index) => `${String(Math.floor(index / 2)).padStart(2, '0')}:${index % 2 ? '30' : '00'}`,
)

// label: the option, after "Toutes les"; describes it.
export const INTERVALS: { minutes: number; label: string }[] = [
  { minutes: 30, label: '30 minutes' },
  { minutes: 60, label: 'heures' },
  ...[2, 3, 4, 6, 8, 12].map((hours) => ({ minutes: hours * 60, label: `${hours} heures` })),
  { minutes: 1440, label: '24 heures' },
  { minutes: 2880, label: '48 heures' },
  { minutes: 4320, label: '72 heures' },
  { minutes: 10080, label: 'semaines' },
]

export function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Paris'
}

const dateTime = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })

// "09:30:00" (as the backend returns it) -> "09:30".
function hhmm(time: string | null | undefined): string {
  return (time ?? '').slice(0, 5).replace(':', 'h')
}

export function describeSchedule(schedule: RefreshSchedule | null): string {
  if (!schedule) return 'Jamais'
  switch (schedule.kind) {
    case 'once':
      return `Une fois, le ${dateTime.format(new Date(schedule.run_at ?? ''))}`
    case 'daily':
      return `Tous les jours à ${hhmm(schedule.time_of_day)}`
    case 'weekly': {
      const days = (schedule.weekdays ?? []).map((day) => WEEKDAYS[day]?.toLowerCase()).join(', ')
      return `Chaque ${days} à ${hhmm(schedule.time_of_day)}`
    }
    case 'interval': {
      const label = INTERVALS.find((option) => option.minutes === schedule.interval_minutes)?.label
      return `Toutes les ${label ?? `${schedule.interval_minutes} minutes`}`
    }
  }
}
