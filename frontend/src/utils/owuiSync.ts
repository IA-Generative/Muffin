import type { OwuiSyncCounts, OwuiSyncRun } from '../types/owuiSync'

export type Tone = 'info' | 'success' | 'warning' | 'error'

// How a synchronisation with Open WebUI reads on the administrators' page (#466): where it is, and whether it went well.
export function runStatus(run: Pick<OwuiSyncRun, 'status' | 'stalled' | 'withProblems'>): { label: string; tone: Tone } {
  if (run.status === 'failed') return { label: 'Échec', tone: 'error' }
  if (run.status === 'running') {
    return run.stalled ? { label: 'Interrompue', tone: 'error' } : { label: 'En cours', tone: 'info' }
  }
  return run.withProblems ? { label: 'Terminée avec des problèmes', tone: 'warning' } : { label: 'Terminée', tone: 'success' }
}

// The rows of the account, in the order a run goes through the objects, leaving out a kind the account does not have.
export function accountRows(
  account: { groups?: OwuiSyncCounts; knowledgeBases?: OwuiSyncCounts; files?: OwuiSyncCounts } | null,
): { label: string; counts: OwuiSyncCounts }[] {
  if (!account) return []
  return [
    { label: 'Groupes', counts: account.groups },
    { label: 'Knowledge bases', counts: account.knowledgeBases },
    { label: 'Fichiers', counts: account.files },
  ].filter((row): row is { label: string; counts: OwuiSyncCounts } => row.counts !== undefined)
}
