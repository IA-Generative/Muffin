import { ref } from 'vue'

// Chrome/Edge desktop ship SpeechRecognition (webkit-prefixed); Firefox and Safari don't
// support it at all as of this writing - isSupported lets the UI hide/disable the mic button
// and show a browser recommendation instead of a button that silently does nothing.
const SpeechRecognitionCtor: typeof window.SpeechRecognition | undefined =
  typeof window !== 'undefined' ? (window.SpeechRecognition ?? window.webkitSpeechRecognition) : undefined

const isSupported = SpeechRecognitionCtor !== undefined

const isListening = ref(false)
const error = ref<string | null>(null)

let recognition: SpeechRecognition | null = null

function start(onResult: (transcript: string, isFinal: boolean) => void) {
  if (!isSupported || isListening.value) return
  error.value = null

  recognition = new SpeechRecognitionCtor!()
  recognition.lang = navigator.language || 'fr-FR'
  // Interim results so the composer shows live feedback while speaking, not just a silent
  // wait until the browser decides speech has ended.
  recognition.interimResults = true
  recognition.continuous = true

  recognition.onresult = (event: SpeechRecognitionEvent) => {
    let transcript = ''
    let isFinal = false
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript
      if (event.results[i].isFinal) isFinal = true
    }
    onResult(transcript, isFinal)
  }

  recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
    // "not-allowed" is what the spec actually defines for a denied/blocked mic permission -
    // "permission-denied" was a legacy value some old Chrome builds used, never a real member
    // of the standard error code union.
    error.value =
      event.error === 'not-allowed'
        ? 'Accès au micro refusé - autorisez-le dans les paramètres du navigateur pour utiliser la dictée vocale.'
        : 'La dictée vocale a rencontré un problème. Réessayez, ou écrivez votre message.'
    isListening.value = false
  }

  recognition.onend = () => {
    isListening.value = false
  }

  recognition.start()
  isListening.value = true
}

function stop() {
  recognition?.stop()
  isListening.value = false
}

export function useVoiceInput() {
  return { isSupported, isListening, error, start, stop }
}
