const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface DraftImage {
  id: string
  description: string
  section: { heading: string | null; occurrence: number } | null
  afterParagraph: number | null
  // A file was dropped for this spot but isn't in the draft yet.
  uploaded: boolean
  // It is in the draft now.
  inserted: boolean
}

export interface DocumentDraft {
  id: string
  // pending: a worker job is running; ready: there is something to look at; failed: the edit job failed.
  status: 'pending' | 'ready' | 'failed'
  // Which job is running (or ran last): the edit itself, or the insertion of dropped images.
  jobKind: 'edit' | 'images'
  prompt: string
  baseRevision: number
  format: 'odt' | 'md'
  // False: the agent changed nothing and `operationsSummary` is its explanation.
  edited: boolean
  operationsSummary: string
  error: string | null
  // What GET .../draft/preview serves: the PDF of an edited ODT, the text of an edited Markdown.
  preview: 'pdf' | 'markdown' | null
  pendingImages: DraftImage[]
  expiresAt: string | null
  createdAt: string
}

// Backend response shape (snake_case) - see backend/app/schemas/document_draft.py.
interface DraftOut {
  id: string
  status: DocumentDraft['status']
  job_kind: DocumentDraft['jobKind']
  prompt: string
  base_revision: number
  format: DocumentDraft['format']
  edited: boolean
  operations_summary: string
  error: string | null
  preview: DocumentDraft['preview']
  pending_images: {
    id: string
    description: string
    section: DraftImage['section']
    after_paragraph: number | null
    uploaded: boolean
    inserted: boolean
  }[]
  expires_at: string | null
  created_at: string
}

function toDraft(raw: DraftOut): DocumentDraft {
  return {
    id: raw.id,
    status: raw.status,
    jobKind: raw.job_kind,
    prompt: raw.prompt,
    baseRevision: raw.base_revision,
    format: raw.format,
    edited: raw.edited,
    operationsSummary: raw.operations_summary,
    error: raw.error,
    preview: raw.preview,
    pendingImages: raw.pending_images.map((image) => ({
      id: image.id,
      description: image.description,
      section: image.section,
      afterParagraph: image.after_paragraph,
      uploaded: image.uploaded,
      inserted: image.inserted,
    })),
    expiresAt: raw.expires_at,
    createdAt: raw.created_at,
  }
}

// What a refused action means for the user - `message` is ready to display as is.
export class DraftError extends Error {}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

// The backend answers a refusal with `detail: {code, message?, ...}` (a plain string for the 404s and
// 422s). Its own French message is used when it has one; the rest are worded here.
async function toError(response: Response): Promise<DraftError> {
  let detail: unknown = {}
  try {
    detail = (await response.json()).detail ?? {}
  } catch {
    // Not JSON - fall through to the status-based messages.
  }
  const body = typeof detail === 'object' && detail !== null ? (detail as Record<string, unknown>) : {}
  if (response.status === 409 && body.code === 'document_locked') {
    const who = body.held_by_me ? 'dans une autre session de votre compte' : `par ${body.locked_by_display ?? 'quelqu’un'}`
    const until = typeof body.expires_at === 'string' ? ` jusqu'à ${formatTime(body.expires_at)}` : ''
    return new DraftError(`Ce document est en cours de modification ${who}${until}.`)
  }
  if (response.status === 409 && body.code === 'revision_conflict') {
    return new DraftError('Le document a été modifié depuis cette proposition : refusez-la et refaites la demande.')
  }
  if (response.status === 409 && typeof body.message === 'string') return new DraftError(body.message)
  if (response.status === 404) return new DraftError('Cette proposition n’existe plus : elle a été refusée ou a expiré.')
  if (response.status === 415) {
    return new DraftError('Seules les images PNG, JPEG et GIF d’au plus 10 Mo sont acceptées.')
  }
  if (response.status === 422) return new DraftError('Les images ne sont pas prises en charge pour ce format de document.')
  return new DraftError(`L’opération a échoué (${response.status}).`)
}

function draftUrl(collectionId: string, documentId: string, suffix = ''): string {
  return `${API_BASE_URL}/api/collections/${collectionId}/documents/${documentId}/draft${suffix}`
}

async function send(
  url: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<Response> {
  const { json, ...rest } = init
  const response = await fetch(url, {
    credentials: 'include',
    ...rest,
    headers: json === undefined ? rest.headers : { 'Content-Type': 'application/json', ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  })
  if (!response.ok) throw await toError(response)
  return response
}

// null when the document has no draft (never had one, or it was validated, refused or lapsed). Reading
// it renews its lock server-side, so polling a running job also keeps the draft alive.
async function fetchDraft(collectionId: string, documentId: string): Promise<DocumentDraft | null> {
  const response = await fetch(draftUrl(collectionId, documentId), { credentials: 'include' })
  if (response.status === 404) return null
  if (!response.ok) throw await toError(response)
  return toDraft(await response.json())
}

async function createDraft(collectionId: string, documentId: string, prompt: string): Promise<DocumentDraft> {
  return toDraft(await (await send(draftUrl(collectionId, documentId), { method: 'POST', json: { prompt } })).json())
}

async function adjustDraft(collectionId: string, documentId: string, prompt: string): Promise<DocumentDraft> {
  const response = await send(draftUrl(collectionId, documentId, '/adjust'), { method: 'POST', json: { prompt } })
  return toDraft(await response.json())
}

async function refuseDraft(collectionId: string, documentId: string): Promise<void> {
  await send(draftUrl(collectionId, documentId), { method: 'DELETE' })
}

// Promotes the draft to the document's next revision; the document is then reindexed.
async function validateDraft(collectionId: string, documentId: string): Promise<void> {
  await send(draftUrl(collectionId, documentId, '/validate'), { method: 'POST' })
}

async function uploadImage(collectionId: string, documentId: string, imageId: string, file: File): Promise<DocumentDraft> {
  const formData = new FormData()
  formData.append('file', file)
  const response = await send(draftUrl(collectionId, documentId, `/images/${encodeURIComponent(imageId)}`), {
    method: 'PUT',
    body: formData,
  })
  return toDraft(await response.json())
}

async function insertImages(collectionId: string, documentId: string): Promise<DocumentDraft> {
  const response = await send(draftUrl(collectionId, documentId, '/images/insert'), { method: 'POST' })
  return toDraft(await response.json())
}

export type DraftPreview = { kind: 'pdf'; url: string } | { kind: 'markdown'; text: string }

// The PDF comes back as a blob URL (the caller revokes it with releasePreview): an <iframe> can't send
// the session cookie to the API origin the way fetch does, and the backend never hands out a storage URL.
async function fetchPreview(collectionId: string, documentId: string, kind: 'pdf' | 'markdown'): Promise<DraftPreview> {
  const response = await send(draftUrl(collectionId, documentId, '/preview'))
  if (kind === 'markdown') return { kind, text: await response.text() }
  return { kind, url: URL.createObjectURL(await response.blob()) }
}

function releasePreview(preview: DraftPreview | null): void {
  if (preview?.kind === 'pdf') URL.revokeObjectURL(preview.url)
}

export function useDocumentDraft() {
  return {
    fetchDraft,
    createDraft,
    adjustDraft,
    refuseDraft,
    validateDraft,
    uploadImage,
    insertImages,
    fetchPreview,
    releasePreview,
  }
}
