import { computed, ref } from 'vue'
import { engineIsDown, formatClock } from '../utils/voice'
import { RecorderError, useVoiceRecorder } from './useVoiceRecorder'
import { useVoiceInput } from './useVoiceInput'
import { useVoiceStatus } from './useVoiceStatus'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type OnText = (text: string, isFinal: boolean) => void

// Le moteur du serveur a échoué (injoignable, route absente...) : pour le reste de la session, la dictée retombe sur celle du
// navigateur quand il en a une, au lieu de proposer un micro qui échouera encore.
const serverDown = ref(false)
const transcribing = ref(false)
const serverError = ref<string | null>(null)
// Ce que lit un lecteur d'écran (région `aria-live`) : les changements d'état, jamais le temps qui passe seconde par seconde.
const announcement = ref('')

let pending: OnText | null = null

async function refusal(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail?.message === 'string') return body.detail.message
  } catch {
    // Pas de corps à lire.
  }
  return 'La transcription a échoué. Réessayez, ou écrivez votre message.'
}

// La dictée du chat (#517) : enregistrer puis transcrire par le serveur quand l'administrateur l'a mis en place, sinon la
// dictée du navigateur comme avant. Le composeur n'a qu'un bouton : c'est ici qu'on choisit.
export function useDictation() {
  const browser = useVoiceInput()
  const recorder = useVoiceRecorder()
  const { status } = useVoiceStatus()

  const mode = computed<'server' | 'browser'>(() =>
    status.value.transcription.mode === 'server' && recorder.isSupported && !(serverDown.value && browser.isSupported)
      ? 'server'
      : 'browser',
  )
  const supported = computed(() => (mode.value === 'server' ? true : browser.isSupported))
  const listening = computed(() => (mode.value === 'server' ? recorder.isRecording.value : browser.isListening.value))
  const error = computed(() => serverError.value ?? browser.error.value)
  const clock = computed(() => formatClock(recorder.elapsed.value))
  const limit = computed(() => formatClock(status.value.transcription.maxSeconds))
  const destination = computed(() => (mode.value === 'server' ? status.value.transcription.destination : 'browser'))

  async function finish() {
    const onText = pending
    pending = null
    announcement.value = 'Transcription en cours.'
    transcribing.value = true
    try {
      const recording = await recorder.stop()
      if (!recording) {
        serverError.value = 'L’enregistrement est vide. Réessayez en parlant plus près du micro.'
        return
      }
      const form = new FormData()
      form.append('file', recording.blob, 'voice')
      form.append('duration_seconds', recording.seconds.toFixed(1))
      // Le français de l'interface comme indice, sauf si l'administrateur a fixé la langue.
      if (status.value.transcription.language === 'auto') {
        form.append('language', (navigator.language || 'fr').split('-')[0])
      }
      const response = await fetch(`${API_BASE_URL}/api/transcriptions`, { method: 'POST', credentials: 'include', body: form })
      if (!response.ok) {
        const message = await refusal(response)
        if (engineIsDown(response.status)) {
          serverDown.value = true
          serverError.value = browser.isSupported
            ? `${message} La dictée de votre navigateur sera utilisée à la place.`
            : `${message} Écrivez votre message.`
        } else {
          serverError.value = message
        }
        announcement.value = 'La transcription a échoué.'
        return
      }
      const result = await response.json()
      const text = typeof result.text === 'string' ? result.text.trim() : ''
      if (!text) {
        serverError.value = 'Aucun texte n’a été reconnu. Réessayez en parlant plus près du micro.'
        announcement.value = 'Aucun texte reconnu.'
        return
      }
      onText?.(text, true)
      announcement.value = 'Texte ajouté au message.'
    } catch {
      serverError.value = 'La transcription a échoué. Réessayez, ou écrivez votre message.'
      announcement.value = 'La transcription a échoué.'
    } finally {
      transcribing.value = false
    }
  }

  async function start(onText: OnText) {
    serverError.value = null
    announcement.value = ''
    if (mode.value === 'browser') {
      browser.start(onText)
      return
    }
    pending = onText
    try {
      await recorder.start(status.value.transcription.maxSeconds, () => {
        announcement.value = 'Durée maximale atteinte : l’enregistrement s’arrête.'
        void finish()
      })
      announcement.value = 'Enregistrement en cours. Appuyez de nouveau pour arrêter et transcrire.'
    } catch (error) {
      pending = null
      serverError.value = error instanceof RecorderError ? error.message : 'L’enregistrement n’a pas pu démarrer.'
    }
  }

  // Arrête l'enregistrement et lance la transcription (serveur), ou arrête la dictée du navigateur.
  function stop() {
    if (mode.value === 'browser') browser.stop()
    else void finish()
  }

  function cancel() {
    if (mode.value === 'browser') {
      browser.stop()
      return
    }
    pending = null
    recorder.cancel()
    announcement.value = 'Enregistrement annulé.'
  }

  return {
    mode,
    supported,
    listening,
    transcribing,
    error,
    announcement,
    clock,
    limit,
    level: recorder.level,
    destination,
    start,
    stop,
    cancel,
  }
}
