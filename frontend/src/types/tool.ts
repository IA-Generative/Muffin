export type ToolVisibility = 'private' | 'groups' | 'all'
export type ToolAuthMode = 'none' | 'bearer'

export interface Tool {
  // Ce par quoi le chat désigne un outil : `internal.calculatrice`, ou l'identifiant de l'outil d'un serveur.
  ref: string
  name: string
  description: string
  inputSchema: Record<string, unknown>
  serverId: string | null
  serverName: string | null
  sideEffect: boolean
  // Faux quand l'outil est retiré pour cette conversation. Un outil qui modifie des données reste disponible : il est proposé à la personne.
  available: boolean
  reason: string | null
}

export interface ToolServer {
  id: string
  name: string
  url: string
  authMode: ToolAuthMode
  hasToken: boolean
  visibility: ToolVisibility
  groupIds: string[]
  enabled: boolean
  isOwner: boolean
  lastSyncedAt: string | null
  lastError: string | null
  tools: Tool[]
}

export interface ToolServerDraft {
  name: string
  url: string
  authMode: ToolAuthMode
  token: string
  visibility: ToolVisibility
  groupIds: string[]
}
