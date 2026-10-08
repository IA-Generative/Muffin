const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const LOCK_HEADER = 'X-Document-Lock-Token'

export interface DocumentRevision {
  number: number
  filename: string
  format: 'odt' | 'md'
  origin: 'upload' | 'chat' | 'ui' | 'restore'
  createdByDisplay: string | null
  restoredFromNumber: number | null
  createdAt: string
  isCurrent: boolean
}

export interface DocumentLock {
  lockedByDisplay: string | null
  expiresAt: string
  // The lock belongs to the calling user - e.g. their own session in another tab.
  heldByMe: boolean
}

// Backend response shapes (snake_case) - see backend/app/schemas/document.py.
interface RevisionOut {
  number: number
  filename: string
  format: DocumentRevision['format']
  origin: DocumentRevision['origin']
  created_by_display: string | null
  restored_from_number: number | null
  created_at: string
  is_current: boolean
}

interface LockOut {
  locked_by_display: string | null
  expires_at: string
  held_by_me: boolean
}

function toRevision(raw: RevisionOut): DocumentRevision {
  return {
    number: raw.number,
    filename: raw.filename,
    format: raw.format,
    origin: raw.origin,
    createdByDisplay: raw.created_by_display,
    restoredFromNumber: raw.restored_from_number,
    createdAt: raw.created_at,
    isCurrent: raw.is_current,
  }
}

function toLock(raw: LockOut): DocumentLock {
  return { lockedByDisplay: raw.locked_by_display, expiresAt: raw.expires_at, heldByMe: raw.held_by_me }
}

// What a write refused by the backend means for the user - `message` is ready to display as is.
// `stale` (the revision or the lock moved on) means "reload the history, then try again".
export class LivingDocumentError extends Error {
  stale: boolean

  constructor(message: string, stale = false) {
    super(message)
    this.stale = stale
  }
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

// Turns a failed response into the right error: the backend's 409s carry a machine-readable
// `detail.code` (document_locked, revision_conflict, lock_lost), the rest are plain statuses.
async function toError(response: Response): Promise<LivingDocumentError> {
  let detail: { code?: string; locked_by_display?: string | null; expires_at?: string; held_by_me?: boolean } = {}
  try {
    detail = (await response.json()).detail ?? {}
  } catch {
    // Not JSON - fall through to the status-based messages.
  }
  if (response.status === 409 && detail.code === 'document_locked') {
    const until = detail.expires_at ? ` jusqu'à ${formatTime(detail.expires_at)}` : ''
    const who = detail.held_by_me ? 'dans une autre session de votre compte' : `par ${detail.locked_by_display ?? 'quelqu’un'}`
    return new LivingDocumentError(`Ce document est en cours de modification ${who}${until}.`, true)
  }
  if (response.status === 409 && detail.code === 'revision_conflict') {
    return new LivingDocumentError(
      'Ce document a été modifié entre-temps. L’historique a été rechargé, réessayez.',
      true,
    )
  }
  if (response.status === 409 && detail.code === 'lock_lost') {
    return new LivingDocumentError('Le verrou d’édition a expiré. Réessayez.', true)
  }
  if (response.status === 415) return new LivingDocumentError('Seuls les fichiers .odt et .md sont acceptés.')
  if (response.status === 422) {
    return new LivingDocumentError('Le nouveau fichier doit avoir le même format que le document (ODT ou Markdown).')
  }
  return new LivingDocumentError(`L’opération a échoué (${response.status}).`)
}

function documentUrl(collectionId: string, documentId: string, suffix = ''): string {
  return `${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}${suffix}`
}

async function fetchRevisions(collectionId: string, documentId: string): Promise<DocumentRevision[]> {
  const response = await fetch(documentUrl(collectionId, documentId, '/revisions'), { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status}`)
  return (await response.json() as RevisionOut[]).map(toRevision)
}

async function fetchLock(collectionId: string, documentId: string): Promise<DocumentLock | null> {
  const response = await fetch(documentUrl(collectionId, documentId, '/lock'), { credentials: 'include' })
  if (!response.ok) throw new Error(`${response.status}`)
  const body: LockOut | null = await response.json()
  return body ? toLock(body) : null
}

// Takes the soft lock, runs the write with its token, and always lets go of the lock if the
// write didn't succeed (a successful write releases it server-side). Best-effort release: the
// lock expires on its own anyway.
async function withLock(
  collectionId: string,
  documentId: string,
  write: (headers: Record<string, string>) => Promise<Response>,
): Promise<void> {
  const grantResponse = await fetch(documentUrl(collectionId, documentId, '/lock'), {
    method: 'POST',
    credentials: 'include',
  })
  if (!grantResponse.ok) throw await toError(grantResponse)
  const { token } = (await grantResponse.json()) as { token: string }
  const headers = { [LOCK_HEADER]: token }

  let response: Response
  try {
    response = await write(headers)
  } catch (error) {
    await releaseLock(collectionId, documentId, token)
    throw error
  }
  if (!response.ok) {
    await releaseLock(collectionId, documentId, token)
    throw await toError(response)
  }
}

async function releaseLock(collectionId: string, documentId: string, token: string): Promise<void> {
  try {
    await fetch(documentUrl(collectionId, documentId, '/lock'), {
      method: 'DELETE',
      credentials: 'include',
      headers: { [LOCK_HEADER]: token },
    })
  } catch {
    // Ignored: the lock expires by itself.
  }
}

// `baseRevision` is the revision the user was looking at - the backend refuses the write if the
// document moved on since (revision_conflict), instead of silently overwriting someone's change.
async function replaceDocument(
  collectionId: string,
  documentId: string,
  file: File,
  baseRevision: number,
): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)
  await withLock(collectionId, documentId, (headers) =>
    fetch(documentUrl(collectionId, documentId, `/content?base_revision=${baseRevision}`), {
      method: 'PUT',
      credentials: 'include',
      headers,
      body: formData,
    }),
  )
}

async function restoreRevision(
  collectionId: string,
  documentId: string,
  revisionNumber: number,
  baseRevision: number,
): Promise<void> {
  await withLock(collectionId, documentId, (headers) =>
    fetch(documentUrl(collectionId, documentId, `/revisions/${revisionNumber}/restore?base_revision=${baseRevision}`), {
      method: 'POST',
      credentials: 'include',
      headers,
    }),
  )
}

// Fetched (not a plain link) so the session cookie always goes along and a failure can be
// reported, then handed to the browser as a file save - the backend streams it, there is no
// direct storage URL. `revisionNumber` omitted downloads the current revision.
async function downloadDocument(
  collectionId: string,
  documentId: string,
  fallbackName: string,
  revisionNumber?: number,
): Promise<void> {
  const query = revisionNumber === undefined ? '' : `?revision=${revisionNumber}`
  const response = await fetch(documentUrl(collectionId, documentId, `/content${query}`), { credentials: 'include' })
  if (!response.ok) throw new LivingDocumentError(`Le téléchargement a échoué (${response.status}).`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallbackName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// Prefers the RFC 5987 filename* (accents, spaces) over the ASCII fallback.
function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      // Malformed escape - fall through to the plain filename.
    }
  }
  return /filename="([^"]+)"/i.exec(header)?.[1] ?? null
}

export function useLivingDocuments() {
  return { fetchRevisions, fetchLock, replaceDocument, restoreRevision, downloadDocument }
}
