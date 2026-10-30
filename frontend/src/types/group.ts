export interface Group {
  id: string
  name: string
  description: string
  // Made in Muffin ('muffin') or copied from Open WebUI ('owui'): a copied group is read only (#455).
  source: string
  isOwner: boolean
  // May rename it, delete it and manage who is in: its owner or an administrator - never a copied group.
  canManage: boolean
  memberCount: number
  // Invitations waiting for a person to sign in - counted for those who manage the group only.
  pendingCount: number
}

export interface GroupMember {
  id: string
  status: 'active' | 'pending'
  // A name to show, or the masked email of an invitation ("j***@e***.com") - never a Keycloak subject.
  display: string
}
