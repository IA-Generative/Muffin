import { computed, ref } from 'vue'
import type { VoiceDestination } from '../utils/voice'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface VoiceStatus {
  transcription: {
    // `server` : on enregistre puis le serveur transcrit ; `browser` : la dictée du navigateur, comme avant.
    mode: 'server' | 'browser'
    maxSeconds: number
    maxBytes: number
    language: string
    destination: VoiceDestination
  }
  speech: {
    mode: 'server' | 'browser'
    maxChars: number
    destination: VoiceDestination
  }
}

interface VoiceStatusOut {
  transcription: { mode: 'server' | 'browser'; max_seconds: number; max_bytes: number; language: string; destination: VoiceDestination }
  speech: { mode: 'server' | 'browser'; max_chars: number; destination: VoiceDestination }
}

// Tant qu'on ne sait pas, ou si on ne peut pas savoir : le navigateur, comme avant l'existence de cette fonction.
const BROWSER: VoiceStatus = {
  transcription: { mode: 'browser', maxSeconds: 300, maxBytes: 25 * 1024 * 1024, language: 'auto', destination: 'browser' },
  speech: { mode: 'browser', maxChars: 4000, destination: 'browser' },
}

const status = ref<VoiceStatus>(BROWSER)
let loading: Promise<void> | null = null

function toStatus(raw: VoiceStatusOut): VoiceStatus {
  return {
    transcription: {
      mode: raw.transcription.mode,
      maxSeconds: raw.transcription.max_seconds,
      maxBytes: raw.transcription.max_bytes,
      language: raw.transcription.language,
      destination: raw.transcription.destination,
    },
    speech: { mode: raw.speech.mode, maxChars: raw.speech.max_chars, destination: raw.speech.destination },
  }
}

// Une seule lecture par session, partagée par le composeur et les réponses ; `force` pour la refaire (après un réglage).
function loadVoiceStatus(force = false): Promise<void> {
  if (loading && !force) return loading
  loading = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/voice/status`, { credentials: 'include' })
      status.value = response.ok ? toStatus(await response.json()) : BROWSER
    } catch {
      status.value = BROWSER
    }
  })()
  return loading
}

export function useVoiceStatus() {
  void loadVoiceStatus()
  return {
    status,
    transcriptionMode: computed(() => status.value.transcription.mode),
    speechMode: computed(() => status.value.speech.mode),
    loadVoiceStatus,
  }
}
