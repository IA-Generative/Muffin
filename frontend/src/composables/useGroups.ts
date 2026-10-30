import { ref } from 'vue'
import type { Group, GroupMember } from '../types/group'

// Same origin rule as useCollections: the BFF session cookie is scoped to the backend's origin.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface GroupOut {
  id: string
  name: string
  description: string
  source: string
  is_owner: boolean
  can_manage: boolean
  member_count: number
  pending_count: number
}

interface MemberOut {
  id: string
  status: GroupMember['status']
  display: string
}

function toGroup(raw: GroupOut): Group {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    source: raw.source,
    isOwner: raw.is_owner,
    canManage: raw.can_manage,
    memberCount: raw.member_count,
    pendingCount: raw.pending_count,
  }
}

// Module-level singleton, like useCollections: the groups screen and the sharing panel see the same list.
const groups = ref<Group[]>([])
const isLoading = ref(false)
const groupError = ref<string | null>(null)

async function request(path: string, init?: RequestInit): Promise<Response | null> {
  try {
    return await fetch(`${API_BASE_URL}/api/groups${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    groupError.value = 'Le serveur est inaccessible.'
    return null
  }
}

async function refreshGroups() {
  isLoading.value = true
  try {
    const response = await request('')
    if (response?.ok) groups.value = (await response.json() as GroupOut[]).map(toGroup)
  } finally {
    isLoading.value = false
  }
}

// What the server answers when the caller may not do it, or the group is a copy: said plainly, not "failed".
function describe(response: Response, fallback: string): string {
  if (response.status === 403) return "Seuls le propriétaire du groupe ou un administrateur peuvent faire cela."
  if (response.status === 404) return "Ce groupe n'existe plus ou vous n'en faites pas partie."
  if (response.status === 409) return 'Ce groupe est copié depuis Open WebUI : il ne se modifie pas ici.'
  return fallback
}

async function createGroup(name: string, description = ''): Promise<Group | null> {
  groupError.value = null
  const response = await request('', { method: 'POST', body: JSON.stringify({ name, description }) })
  if (!response) return null
  if (!response.ok) {
    groupError.value = 'Échec de la création du groupe.'
    return null
  }
  const group = toGroup(await response.json())
  groups.value = [...groups.value, group].sort((a, b) => a.name.localeCompare(b.name, 'fr'))
  return group
}

async function updateGroup(id: string, changes: { name?: string; description?: string }): Promise<boolean> {
  groupError.value = null
  const response = await request(`/${id}`, { method: 'PATCH', body: JSON.stringify(changes) })
  if (!response) return false
  if (!response.ok) {
    groupError.value = describe(response, 'Échec de la modification du groupe.')
    return false
  }
  const group = toGroup(await response.json())
  groups.value = groups.value.map((item) => (item.id === id ? group : item))
  return true
}

async function deleteGroup(id: string): Promise<boolean> {
  groupError.value = null
  const response = await request(`/${id}`, { method: 'DELETE' })
  if (!response) return false
  if (!response.ok) {
    groupError.value = describe(response, 'Échec de la suppression du groupe.')
    return false
  }
  groups.value = groups.value.filter((item) => item.id !== id)
  return true
}

async function fetchMembers(id: string): Promise<GroupMember[]> {
  const response = await request(`/${id}/members`)
  if (!response?.ok) return []
  return (await response.json() as MemberOut[]).map((member) => ({ ...member }))
}

// By email: nothing is looked up - an invitation that becomes a member when that person signs in. The
// answer never says whether the address has an account.
async function addMember(id: string, email: string): Promise<boolean> {
  groupError.value = null
  const response = await request(`/${id}/members`, { method: 'POST', body: JSON.stringify({ email }) })
  if (!response) return false
  if (response.status === 409) {
    const detail = (await response.json().catch(() => ({})))?.detail as string | undefined
    groupError.value = detail?.startsWith('Already')
      ? 'Cette personne est déjà dans le groupe, ou invitée.'
      : describe(response, "Échec de l'ajout du membre.")
    return false
  }
  if (!response.ok) {
    groupError.value = describe(response, "Échec de l'ajout du membre.")
    return false
  }
  await refreshGroups()
  return true
}

async function removeMember(id: string, memberId: string): Promise<boolean> {
  groupError.value = null
  const response = await request(`/${id}/members/${memberId}`, { method: 'DELETE' })
  if (!response) return false
  if (!response.ok) {
    groupError.value = describe(response, 'Échec du retrait du membre.')
    return false
  }
  await refreshGroups()
  return true
}

export function useGroups() {
  return {
    groups,
    isLoading,
    groupError,
    refreshGroups,
    createGroup,
    updateGroup,
    deleteGroup,
    fetchMembers,
    addMember,
    removeMember,
  }
}
