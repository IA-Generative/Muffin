// The synchronisation with Open WebUI (#453), as the administrators' page shows it (#466).
export interface OwuiSyncCounts {
  seen: number
  errors: number
  dropped: number
  unlisted?: number
  inconsistent?: number
}

export interface OwuiSyncAccount {
  groups?: OwuiSyncCounts
  knowledgeBases?: OwuiSyncCounts
  files?: OwuiSyncCounts
}

export interface OwuiSyncRun {
  runId: string
  status: 'running' | 'done' | 'failed'
  startedAt: string
  finishedAt: string | null
  account: OwuiSyncAccount | null
  error: string | null
  // It never reported an end after hours: a worker died with it.
  stalled: boolean
  // It ended, but with objects in error or vectors that do not match.
  withProblems: boolean
}

export type SyncedCollectionState = 'copied' | 'adopting' | 'adopted'

export interface SyncedCollection {
  id: string
  name: string
  externalId: string
  state: SyncedCollectionState
  documentCount: number
  summaryCount: number
  syncedAt: string | null
  problems: string[]
}
