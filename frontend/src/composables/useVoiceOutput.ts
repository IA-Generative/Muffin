import { computed, ref } from 'vue'
import { chunkForSpeech, guessLanguage } from '../utils/voice'
import { useVoiceStatus } from './useVoiceStatus'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// speechSynthesis (unlike SpeechRecognition, see useVoiceInput.ts) is well supported across
// Chrome, Firefox, Safari and Edge - no browser-recommendation fallback needed here.
const browserSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

// Id of the message currently being read aloud, null when nothing is - module-level singleton
// (same pattern as useVoiceInput/useChat) so starting a new reading always stops whatever
// utterance was already playing, never two voices overlapping.
const speakingId = ref<string | null>(null)
// La lecture par le serveur a échoué (injoignable, route absente...) : pour le reste de la session on lit avec la voix du
// navigateur quand il en a une, au lieu de proposer une lecture qui échouera encore (#517).
const serverDown = ref(false)

// What is playing now, so that `stop` ends the right thing: a token that changes with each reading (a stale reading that
// comes back from the network after another began must not start playing), the audio element, and the requests in flight.
let session = 0
let audio: HTMLAudioElement | null = null
let controller: AbortController | null = null

function speakInBrowser(id: string, text: string, lang?: string) {
  if (!browserSupported || !text.trim()) {
    if (speakingId.value === id) speakingId.value = null
    return
  }
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  if (lang) utterance.lang = lang
  utterance.onend = () => {
    if (speakingId.value === id) speakingId.value = null
  }
  utterance.onerror = () => {
    if (speakingId.value === id) speakingId.value = null
  }
  speakingId.value = id
  window.speechSynthesis.speak(utterance)
}

async function fetchSpeech(text: string, language: string | undefined, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/speech`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language }),
    signal,
  })
  if (!response.ok) throw new Error(`speech ${response.status}`)
  return response.blob()
}

function playBlob(blob: Blob, mine: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (mine !== session) {
      resolve()
      return
    }
    const url = URL.createObjectURL(blob)
    const element = new Audio(url)
    audio = element
    const done = () => {
      URL.revokeObjectURL(url)
      if (audio === element) audio = null
    }
    element.onended = () => {
      done()
      resolve()
    }
    element.onerror = () => {
      done()
      reject(new Error('audio'))
    }
    element.play().catch((error) => {
      done()
      reject(error)
    })
  })
}

// La lecture par le serveur (#517) : le texte est découpé, chaque morceau est demandé puis lu, le suivant étant demandé
// pendant que le précédent joue. Un échec avant le premier son retombe sur la voix du navigateur.
async function speakFromServer(id: string, text: string, lang: string | undefined, maxChars: number) {
  const mine = ++session
  controller = new AbortController()
  const { signal } = controller
  const language = lang ?? guessLanguage(text)
  const chunks = chunkForSpeech(text, maxChars)
  speakingId.value = id
  let played = false
  try {
    let next: Promise<Blob> | null = fetchSpeech(chunks[0], language, signal)
    for (let index = 0; index < chunks.length; index++) {
      const blob = await next!
      if (mine !== session) return
      next = index + 1 < chunks.length ? fetchSpeech(chunks[index + 1], language, signal) : null
      next?.catch(() => undefined)
      played = true
      await playBlob(blob, mine)
      if (mine !== session) return
    }
    if (speakingId.value === id) speakingId.value = null
  } catch {
    if (mine !== session) return
    if (!played && browserSupported) {
      serverDown.value = true
      speakInBrowser(id, text, lang)
    } else if (speakingId.value === id) {
      speakingId.value = null
    }
  }
}

function stop() {
  session += 1
  controller?.abort()
  controller = null
  if (audio) {
    audio.pause()
    audio = null
  }
  if (browserSupported) window.speechSynthesis.cancel()
  speakingId.value = null
}

export function useVoiceOutput() {
  const { status } = useVoiceStatus()
  const useServer = computed(() => status.value.speech.mode === 'server' && !(serverDown.value && browserSupported))
  const isSupported = computed(() => status.value.speech.mode === 'server' || browserSupported)

  function speak(id: string, text: string, lang?: string) {
    if (!text.trim()) return
    stop()
    if (useServer.value) void speakFromServer(id, text, lang, status.value.speech.maxChars)
    else speakInBrowser(id, text, lang)
  }

  // Starts reading `id`/`text`, or stops if `id` is already the one being read - the single
  // action a toggle button or keyboard shortcut needs.
  function toggle(id: string, text: string, lang?: string) {
    if (speakingId.value === id) stop()
    else speak(id, text, lang)
  }

  return { isSupported, speakingId, speak, stop, toggle, destination: computed(() => status.value.speech.destination) }
}
