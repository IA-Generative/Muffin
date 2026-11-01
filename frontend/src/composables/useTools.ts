import { ref } from 'vue'
import type { Tool, ToolAuthMode, ToolServer, ToolServerDraft, ToolVisibility } from '../types/tool'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface ToolOut {
  ref: string
  name: string
  description: string
  input_schema: Record<string, unknown>
  server_id: string | null
  server_name: string | null
  side_effect: boolean
  available: boolean
  reason: string | null
}

interface ServerOut {
  id: string
  name: string
  url: string
  auth_mode: ToolAuthMode
  has_token: boolean
  visibility: ToolVisibility
  group_ids: string[]
  enabled: boolean
  is_owner: boolean
  last_synced_at: string | null
  last_error: string | null
  tools: ToolOut[]
}

export function toTool(raw: ToolOut): Tool {
  return {
    ref: raw.ref,
    name: raw.name,
    description: raw.description,
    inputSchema: raw.input_schema,
    serverId: raw.server_id,
    serverName: raw.server_name,
    sideEffect: raw.side_effect,
    available: raw.available,
    reason: raw.reason,
  }
}

function toServer(raw: ServerOut): ToolServer {
  return {
    id: raw.id,
    name: raw.name,
    url: raw.url,
    authMode: raw.auth_mode,
    hasToken: raw.has_token,
    visibility: raw.visibility,
    groupIds: raw.group_ids,
    enabled: raw.enabled,
    isOwner: raw.is_owner,
    lastSyncedAt: raw.last_synced_at,
    lastError: raw.last_error,
    tools: raw.tools.map(toTool),
  }
}

// Module-level singleton, comme useAssistants : la page des outils et le menu du chat voient les mêmes serveurs.
const servers = ref<ToolServer[]>([])
const tools = ref<Tool[]>([])
const isLoading = ref(false)
const toolError = ref<string | null>(null)

async function request(path: string, init?: RequestInit): Promise<Response | null> {
  try {
    return await fetch(`${API_BASE_URL}/api${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    toolError.value = 'Le serveur est inaccessible.'
    return null
  }
}

// Ce que dit le serveur quand une chose n'est pas permise, dit en clair : pour une adresse refusée, la raison vient de lui.
async function describe(response: Response, fallback: string): Promise<string> {
  if (response.status === 403) return 'Seule la personne qui a ajouté ce serveur peut faire cela.'
  if (response.status === 404) return 'Ce serveur n’existe plus ou ne vous est pas partagé.'
  if (response.status === 409) return 'Vous avez atteint le nombre maximal de serveurs d’outils.'
  if (response.status === 422) {
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') return body.detail
    } catch {
      // No body to read.
    }
    return 'Un champ n’est pas valide.'
  }
  return fallback
}

async function refreshServers() {
  isLoading.value = true
  try {
    const response = await request('/tool-servers')
    if (response?.ok) servers.value = ((await response.json()) as ServerOut[]).map(toServer)
  } finally {
    isLoading.value = false
  }
}

// Les outils que la personne peut utiliser (ceux de Muffin et ceux des serveurs qu'elle voit), avec ce qu'une conversation
// en a retiré quand on la donne.
async function refreshTools(conversationId?: string) {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''
  const response = await request(`/tools${query}`)
  if (response?.ok) tools.value = ((await response.json()) as ToolOut[]).map(toTool)
}

function body(draft: ToolServerDraft, editing: boolean): Record<string, unknown> {
  return {
    name: draft.name.trim(),
    url: draft.url.trim(),
    auth_mode: draft.authMode,
    // Absent : le jeton reste (à la modification) ; envoyé : il est remplacé. Jamais relu.
    ...(draft.authMode === 'bearer' && draft.token ? { token: draft.token } : editing ? {} : { token: null }),
    visibility: draft.visibility,
    group_ids: draft.visibility === 'groups' ? draft.groupIds : [],
  }
}

function upsert(server: ToolServer) {
  const known = servers.value.some((item) => item.id === server.id)
  servers.value = known
    ? servers.value.map((item) => (item.id === server.id ? server : item))
    : [...servers.value, server].sort((a, b) => a.name.localeCompare(b.name, 'fr'))
}

async function saveServer(draft: ToolServerDraft, id?: string): Promise<ToolServer | null> {
  toolError.value = null
  const response = await request(id ? `/tool-servers/${id}` : '/tool-servers', {
    method: id ? 'PATCH' : 'POST',
    body: JSON.stringify(body(draft, Boolean(id))),
  })
  if (!response) return null
  if (!response.ok) {
    toolError.value = await describe(response, 'Échec de l’enregistrement du serveur.')
    return null
  }
  const server = toServer(await response.json())
  upsert(server)
  return server
}

async function setEnabled(id: string, enabled: boolean): Promise<boolean> {
  toolError.value = null
  const response = await request(`/tool-servers/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
  if (!response?.ok) {
    if (response) toolError.value = await describe(response, 'Échec du changement.')
    return false
  }
  upsert(toServer(await response.json()))
  return true
}

async function syncServer(id: string): Promise<boolean> {
  toolError.value = null
  const response = await request(`/tool-servers/${id}/sync`, { method: 'POST' })
  if (!response?.ok) {
    if (response) toolError.value = await describe(response, 'Échec de la synchronisation.')
    return false
  }
  upsert(toServer(await response.json()))
  return true
}

async function deleteServer(id: string): Promise<boolean> {
  toolError.value = null
  const response = await request(`/tool-servers/${id}`, { method: 'DELETE' })
  if (!response?.ok) {
    if (response) toolError.value = await describe(response, 'Échec de la suppression.')
    return false
  }
  servers.value = servers.value.filter((item) => item.id !== id)
  return true
}

// Les outils qu'on retire pour une conversation (la liste entière) : le modèle ne les reçoit plus. Ne fait que retirer.
async function setConversationTools(conversationId: string, disabledRefs: string[]): Promise<boolean> {
  toolError.value = null
  const response = await request(`/conversations/${conversationId}/tools`, {
    method: 'PUT',
    body: JSON.stringify({ disabled_refs: disabledRefs }),
  })
  if (!response?.ok) {
    toolError.value = 'Impossible de changer les outils de cette conversation.'
    return false
  }
  await refreshTools(conversationId)
  return true
}

export function useTools() {
  return {
    servers,
    tools,
    isLoading,
    toolError,
    refreshServers,
    refreshTools,
    saveServer,
    setEnabled,
    syncServer,
    deleteServer,
    setConversationTools,
  }
}
