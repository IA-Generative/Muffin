import { computed, ref } from 'vue'
import { imagesOf, prepareImage } from '../utils/imageResize'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface AttachmentStatus {
  // Vrai seulement quand un modèle du hub lit les images : sinon rien n'est proposé, et on dit pourquoi.
  available: boolean
  model: string | null
  maxImages: number
  maxBytes: number
}

// Une image choisie dans le composeur, gardée par le serveur jusqu'à l'envoi du message qui la porte.
export interface StagedImage {
  tempId: string
  name: string
  // L'aperçu local : l'image n'a pas besoin de revenir du serveur pour être montrée.
  previewUrl: string
  status: 'uploading' | 'ready' | 'error'
  // L'identifiant côté serveur, une fois gardée.
  id: string | null
  message: string | null
  width: number | null
  height: number | null
  contentType: string | null
  sizeBytes: number | null
}

const NOT_AVAILABLE: AttachmentStatus = { available: false, model: null, maxImages: 4, maxBytes: 5 * 1024 * 1024 }

// Module-level singleton : le composeur et l'envoi d'un message voient les mêmes images.
const attachmentStatus = ref<AttachmentStatus>({ ...NOT_AVAILABLE })
const staged = ref<StagedImage[]>([])

const uploading = computed(() => staged.value.some((image) => image.status === 'uploading'))

// Ce que le composeur doit savoir pour proposer (ou non) les images. Un refus ou une panne : pas de bouton actif, sans
// message d'erreur - la fonction dépend d'un modèle du hub, son absence n'est pas une panne.
async function loadAttachmentStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/images/attachments/status`, { credentials: 'include' })
    if (!response.ok) {
      attachmentStatus.value = { ...NOT_AVAILABLE }
      return
    }
    const body: { available: boolean; model: string | null; max_images: number; max_bytes: number } = await response.json()
    attachmentStatus.value = {
      available: body.available,
      model: body.model,
      maxImages: body.max_images,
      maxBytes: body.max_bytes,
    }
  } catch {
    attachmentStatus.value = { ...NOT_AVAILABLE }
  }
}

function update(tempId: string, changes: Partial<StagedImage>) {
  staged.value = staged.value.map((image) => (image.tempId === tempId ? { ...image, ...changes } : image))
}

async function messageOf(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
  } catch {
    // No body to read.
  }
  return "Cette image n'a pas pu être jointe."
}

async function upload(tempId: string, file: File) {
  try {
    const sent = await prepareImage(file, attachmentStatus.value.maxBytes)
    const form = new FormData()
    form.append('file', sent)
    const response = await fetch(`${API_BASE_URL}/api/images/attachments`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!response.ok) {
      update(tempId, { status: 'error', message: await messageOf(response) })
      return
    }
    const kept: { id: string; content_type: string; width: number; height: number; size_bytes: number } = await response.json()
    update(tempId, {
      status: 'ready',
      id: kept.id,
      width: kept.width,
      height: kept.height,
      contentType: kept.content_type,
      sizeBytes: kept.size_bytes,
    })
  } catch {
    update(tempId, { status: 'error', message: "Cette image n'a pas pu être envoyée." })
  }
}

// Joint des images (choisies, collées ou déposées) au message en cours : une vignette tout de suite, l'envoi au serveur
// derrière. Ce qui n'est pas une image PNG, JPEG ou WebP est ignoré.
function addImages(files: Iterable<File> | ArrayLike<File> | null | undefined) {
  if (!attachmentStatus.value.available) return
  for (const file of imagesOf(files)) {
    if (staged.value.length >= attachmentStatus.value.maxImages) break
    const tempId = crypto.randomUUID()
    staged.value = [
      ...staged.value,
      {
        tempId,
        name: file.name || 'image',
        previewUrl: URL.createObjectURL(file),
        status: 'uploading',
        id: null,
        message: null,
        width: null,
        height: null,
        contentType: null,
        sizeBytes: null,
      },
    ]
    upload(tempId, file)
  }
}

// La personne retire une vignette avant l'envoi : l'image gardée par le serveur est effacée aussi.
async function removeStagedImage(tempId: string) {
  const image = staged.value.find((item) => item.tempId === tempId)
  if (!image) return
  staged.value = staged.value.filter((item) => item.tempId !== tempId)
  URL.revokeObjectURL(image.previewUrl)
  if (image.id) {
    fetch(`${API_BASE_URL}/api/images/attachments/${image.id}`, { method: 'DELETE', credentials: 'include' }).catch(() => {})
  }
}

// Les images prêtes qui partent avec le message ; la liste est vidée. Les aperçus restent : le message envoyé les montre.
function takeStagedImages(): StagedImage[] {
  const ready = staged.value.filter((image) => image.status === 'ready' && image.id)
  for (const image of staged.value) if (image.status === 'error') URL.revokeObjectURL(image.previewUrl)
  staged.value = []
  return ready
}

export function useImageAttachments() {
  return { attachmentStatus, staged, uploading, loadAttachmentStatus, addImages, removeStagedImage, takeStagedImages }
}
