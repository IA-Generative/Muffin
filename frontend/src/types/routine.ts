export type RoutineKind = 'interval' | 'daily' | 'weekly' | 'monthly'
export type RoutineCondition = 'always' | 'only_if_new'
export type RoutineResultMode = 'new_conversation' | 'single_conversation'
export type RoutineNotify = 'always' | 'failure' | 'never'
export type RoutineState = 'active' | 'paused' | 'suspended'
export type RoutineRunStatus = 'running' | 'succeeded' | 'failed' | 'skipped'

export interface RoutineSchedule {
  kind: RoutineKind
  timezone: string
  // Seulement pour « toutes les n heures » : en minutes.
  intervalMinutes: number | null
  // « HH:MM », l'heure du fuseau de la personne.
  timeOfDay: string | null
  // 0 = lundi.
  weekdays: number[] | null
  dayOfMonth: number | null
}

export interface RoutineRun {
  id: string
  status: RoutineRunStatus
  skipReason: string | null
  trigger: 'schedule' | 'manual'
  error: string | null
  note: string | null
  totalTokens: number
  conversationId: string | null
  startedAt: string
  finishedAt: string | null
  durationSeconds: number | null
}

export interface Routine {
  id: string
  name: string
  question: string
  collectionIds: string[]
  includeDescendants: boolean
  assistantId: string | null
  webSearch: boolean
  schedule: RoutineSchedule
  condition: RoutineCondition
  resultMode: RoutineResultMode
  notify: RoutineNotify
  state: RoutineState
  suspendedReason: string | null
  nextRunAt: string | null
  lastRunAt: string | null
  consecutiveFailures: number
  conversationId: string | null
  lastRun: RoutineRun | null
  createdAt: string
}

// Ce que la personne règle ; le même pour créer et modifier.
export interface RoutineDraft {
  name: string
  question: string
  collectionIds: string[]
  includeDescendants: boolean
  assistantId: string | null
  webSearch: boolean
  schedule: RoutineSchedule
  condition: RoutineCondition
  resultMode: RoutineResultMode
  notify: RoutineNotify
}

export interface RoutineStatus {
  enabled: boolean
  maxActive: number
  minIntervalMinutes: number
  maxRunsPerDay: number
  active: number
  runsToday: number
}

export interface RoutineSettings {
  enabled: boolean
  maxActivePerUser: number
  minIntervalMinutes: number
  maxRunsPerUserPerDay: number
  maxConcurrent: number
  maxConsecutiveFailures: number
  inactiveDays: number
  runTimeoutMinutes: number
}

export interface AdminRoutine {
  id: string
  name: string
  ownerDisplay: string
  schedule: RoutineSchedule
  state: RoutineState
  suspendedReason: string | null
  nextRunAt: string | null
  lastRunAt: string | null
  consecutiveFailures: number
  lastStatus: RoutineRunStatus | null
  tokens30Days: number
}
