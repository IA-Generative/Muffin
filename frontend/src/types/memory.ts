export type MemoryKind = 'preference' | 'habit' | 'context' | 'fact'

export interface MemoryItem {
  id: string
  kind: MemoryKind
  value: string
  // « explicit » : écrit, corrigé ou demandé par la personne ; « inferred » : appris.
  origin: 'explicit' | 'inferred'
  enabled: boolean
  updatedAt: string
  lastUsedAt: string | null
}

export interface MemoryState {
  // La mémoire de la personne est active, et l'administrateur l'autorise.
  enabled: boolean
  available: boolean
  maxItems: number
  valueMaxChars: number
  items: MemoryItem[]
}
