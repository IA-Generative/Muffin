import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface ImageSettings {
  enabled: boolean
  // L'adresse appelée : celle qu'on a saisie, ou celle du hub quand on n'en a pas saisi.
  baseUrl: string | null
  usesHubAddress: boolean
  // Il y a une clé enregistrée, qu'on ne relit jamais.
  hasKey: boolean
  hubAvailable: boolean
  model: string | null
  // Le modèle qui retouche une image ; vide : le même que pour générer.
  editModel: string | null
  size: string
  quality: string | null
  dailyLimit: number
  maxImageBytes: number
  allowedGroups: string[]
  ready: boolean
}

// Ce qu'on envoie : seulement ce qui change. `apiKey` n'est jamais renvoyé par le serveur.
export interface ImageSettingsDraft {
  enabled: boolean
  baseUrl: string
  apiKey: string
  clearKey: boolean
  model: string
  editModel: string
  size: string
  quality: string
  dailyLimit: number
  maxImageBytes: number
  allowedGroups: string[]
}

export interface ImageTestResult {
  ok: boolean
  code: string | null
  message: string | null
  durationMs: number
  responseFormat: string | null
  contentType: string | null
  width: number | null
  height: number | null
  sizeBytes: number | null
  image: string | null
}

interface SettingsOut {
  enabled: boolean
  base_url: string | null
  uses_hub_address: boolean
  has_key: boolean
  hub_available: boolean
  model: string | null
  edit_model: string | null
  size: string
  quality: string | null
  daily_limit: number
  max_image_bytes: number
  allowed_groups: string[]
  ready: boolean
}

interface TestOut {
  ok: boolean
  code: string | null
  message: string | null
  duration_ms: number
  response_format: string | null
  content_type: string | null
  width: number | null
  height: number | null
  size_bytes: number | null
  image: string | null
}

function toSettings(raw: SettingsOut): ImageSettings {
  return {
    enabled: raw.enabled,
    baseUrl: raw.base_url,
    usesHubAddress: raw.uses_hub_address,
    hasKey: raw.has_key,
    hubAvailable: raw.hub_available,
    model: raw.model,
    editModel: raw.edit_model,
    size: raw.size,
    quality: raw.quality,
    dailyLimit: raw.daily_limit,
    maxImageBytes: raw.max_image_bytes,
    allowedGroups: raw.allowed_groups,
    ready: raw.ready,
  }
}

const settings = ref<ImageSettings | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function refuses(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
    if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === 'string') return body.detail[0].msg
  } catch {
    // No body to read.
  }
  return fallback
}

async function loadImageSettings() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/image-generation`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    settings.value = toSettings(await response.json())
  } catch {
    error.value = 'Impossible de récupérer les réglages des images.'
  } finally {
    isLoading.value = false
  }
}

async function saveImageSettings(draft: ImageSettingsDraft): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/image-generation`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: draft.enabled,
        base_url: draft.baseUrl.trim() || null,
        // Absent : la clé reste ; envoyée : elle est remplacée. Jamais relue.
        ...(draft.apiKey.trim() ? { api_key: draft.apiKey.trim() } : {}),
        clear_key: draft.clearKey,
        model: draft.model.trim(),
        edit_model: draft.editModel.trim(),
        size: draft.size.trim() || undefined,
        quality: draft.quality || null,
        daily_limit: draft.dailyLimit,
        max_image_bytes: draft.maxImageBytes,
        allowed_groups: draft.allowedGroups,
      }),
    })
    if (!response.ok) {
      error.value = await refuses(response, "Impossible d'enregistrer les réglages des images.")
      return false
    }
    settings.value = toSettings(await response.json())
    return true
  } catch {
    error.value = "Impossible d'enregistrer les réglages des images."
    return false
  }
}

// Une petite image avec les réglages enregistrés : combien de temps le fournisseur a mis, ou ce qui ne va pas.
async function testImageSettings(): Promise<ImageTestResult | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/image-generation/test`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const raw: TestOut = await response.json()
    return {
      ok: raw.ok,
      code: raw.code,
      message: raw.message,
      durationMs: raw.duration_ms,
      responseFormat: raw.response_format,
      contentType: raw.content_type,
      width: raw.width,
      height: raw.height,
      sizeBytes: raw.size_bytes,
      image: raw.image,
    }
  } catch {
    return null
  }
}

export function useAdminImages() {
  return { settings, isLoading, error, loadImageSettings, saveImageSettings, testImageSettings }
}
