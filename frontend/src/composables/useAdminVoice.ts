import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface VoiceSettings {
  hubAvailable: boolean
  sttEnabled: boolean
  // L'adresse appelée : celle qu'on a saisie, ou celle du hub quand on n'en a pas saisi.
  sttBaseUrl: string | null
  sttUsesHubAddress: boolean
  // Il y a une clé enregistrée, qu'on ne relit jamais.
  sttHasKey: boolean
  sttModel: string | null
  sttLanguage: string
  sttMaxSeconds: number
  sttMaxBytes: number
  sttReady: boolean
  ttsEnabled: boolean
  ttsBaseUrl: string | null
  ttsUsesHubAddress: boolean
  ttsHasKey: boolean
  ttsModel: string | null
  ttsVoice: string | null
  ttsVoiceEn: string | null
  ttsFormat: string
  ttsMaxChars: number
  ttsReady: boolean
}

// Ce qu'on envoie : seulement ce qui change. Les clés ne sont jamais renvoyées par le serveur.
export interface VoiceSettingsDraft {
  sttEnabled: boolean
  sttBaseUrl: string
  sttApiKey: string
  sttClearKey: boolean
  sttModel: string
  sttLanguage: string
  sttMaxSeconds: number
  sttMaxBytes: number
  ttsEnabled: boolean
  ttsBaseUrl: string
  ttsApiKey: string
  ttsClearKey: boolean
  ttsModel: string
  ttsVoice: string
  ttsVoiceEn: string
  ttsFormat: string
  ttsMaxChars: number
}

export interface VoiceTestResult {
  ok: boolean
  code: string | null
  message: string
  durationMs: number
  text: string | null
  contentType: string | null
  audioBytes: number | null
}

interface SettingsOut {
  hub_available: boolean
  stt_enabled: boolean
  stt_base_url: string | null
  stt_uses_hub_address: boolean
  stt_has_key: boolean
  stt_model: string | null
  stt_language: string
  stt_max_seconds: number
  stt_max_bytes: number
  stt_ready: boolean
  tts_enabled: boolean
  tts_base_url: string | null
  tts_uses_hub_address: boolean
  tts_has_key: boolean
  tts_model: string | null
  tts_voice: string | null
  tts_voice_en: string | null
  tts_format: string
  tts_max_chars: number
  tts_ready: boolean
}

interface TestOut {
  ok: boolean
  code: string | null
  message: string
  duration_ms: number
  text: string | null
  content_type: string | null
  audio_bytes: number | null
}

function toSettings(raw: SettingsOut): VoiceSettings {
  return {
    hubAvailable: raw.hub_available,
    sttEnabled: raw.stt_enabled,
    sttBaseUrl: raw.stt_base_url,
    sttUsesHubAddress: raw.stt_uses_hub_address,
    sttHasKey: raw.stt_has_key,
    sttModel: raw.stt_model,
    sttLanguage: raw.stt_language,
    sttMaxSeconds: raw.stt_max_seconds,
    sttMaxBytes: raw.stt_max_bytes,
    sttReady: raw.stt_ready,
    ttsEnabled: raw.tts_enabled,
    ttsBaseUrl: raw.tts_base_url,
    ttsUsesHubAddress: raw.tts_uses_hub_address,
    ttsHasKey: raw.tts_has_key,
    ttsModel: raw.tts_model,
    ttsVoice: raw.tts_voice,
    ttsVoiceEn: raw.tts_voice_en,
    ttsFormat: raw.tts_format,
    ttsMaxChars: raw.tts_max_chars,
    ttsReady: raw.tts_ready,
  }
}

function toTest(raw: TestOut): VoiceTestResult {
  return {
    ok: raw.ok,
    code: raw.code,
    message: raw.message,
    durationMs: raw.duration_ms,
    text: raw.text,
    contentType: raw.content_type,
    audioBytes: raw.audio_bytes,
  }
}

const settings = ref<VoiceSettings | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function refuses(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
    if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === 'string') return body.detail[0].msg
  } catch {
    // Pas de corps à lire.
  }
  return fallback
}

async function loadVoiceSettings() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/voice`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    settings.value = toSettings(await response.json())
  } catch {
    error.value = 'Impossible de récupérer les réglages de la voix.'
  } finally {
    isLoading.value = false
  }
}

async function saveVoiceSettings(draft: VoiceSettingsDraft): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/voice`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stt_enabled: draft.sttEnabled,
        stt_base_url: draft.sttBaseUrl.trim() || null,
        // Absent : la clé reste ; envoyée : elle est remplacée. Jamais relue.
        ...(draft.sttApiKey.trim() ? { stt_api_key: draft.sttApiKey.trim() } : {}),
        stt_clear_key: draft.sttClearKey,
        stt_model: draft.sttModel.trim(),
        stt_language: draft.sttLanguage.trim() || 'auto',
        stt_max_seconds: draft.sttMaxSeconds,
        stt_max_bytes: draft.sttMaxBytes,
        tts_enabled: draft.ttsEnabled,
        tts_base_url: draft.ttsBaseUrl.trim() || null,
        ...(draft.ttsApiKey.trim() ? { tts_api_key: draft.ttsApiKey.trim() } : {}),
        tts_clear_key: draft.ttsClearKey,
        tts_model: draft.ttsModel.trim(),
        tts_voice: draft.ttsVoice.trim(),
        tts_voice_en: draft.ttsVoiceEn.trim(),
        tts_format: draft.ttsFormat,
        tts_max_chars: draft.ttsMaxChars,
      }),
    })
    if (!response.ok) {
      error.value = await refuses(response, 'Impossible d’enregistrer les réglages de la voix.')
      return false
    }
    settings.value = toSettings(await response.json())
    return true
  } catch {
    error.value = 'Impossible d’enregistrer les réglages de la voix.'
    return false
  }
}

// Un essai avec les réglages enregistrés : ce que le service a répondu, le temps mis, ou ce qui ne va pas.
async function testVoice(which: 'transcription' | 'speech'): Promise<VoiceTestResult | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/voice/test-${which}`, { method: 'POST', credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    return toTest(await response.json())
  } catch {
    return null
  }
}

// Fait entendre à l'administrateur la voix du service, par le chemin même que prennent les réponses du chat.
async function playSpeechSample(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/speech`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'Bonjour, ceci est un essai de la lecture à voix haute.', language: 'fr' }),
    })
    if (!response.ok) return false
    const url = URL.createObjectURL(await response.blob())
    const element = new Audio(url)
    element.onended = () => URL.revokeObjectURL(url)
    await element.play()
    return true
  } catch {
    return false
  }
}

export function useAdminVoice() {
  return { settings, isLoading, error, loadVoiceSettings, saveVoiceSettings, testVoice, playSpeechSample }
}
