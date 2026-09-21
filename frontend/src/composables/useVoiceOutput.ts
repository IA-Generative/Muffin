import { ref } from 'vue'

// speechSynthesis (unlike SpeechRecognition, see useVoiceInput.ts) is well supported across
// Chrome, Firefox, Safari and Edge - no browser-recommendation fallback needed here.
const isSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

// Id of the message currently being read aloud, null when nothing is - module-level singleton
// (same pattern as useVoiceInput/useChat) so starting a new reading always stops whatever
// utterance was already playing, never two voices overlapping.
const speakingId = ref<string | null>(null)

function speak(id: string, text: string, lang?: string) {
  if (!isSupported || !text.trim()) return
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

function stop() {
  window.speechSynthesis.cancel()
  speakingId.value = null
}

// Starts reading `id`/`text`, or stops if `id` is already the one being read - the single
// action a toggle button or keyboard shortcut needs.
function toggle(id: string, text: string, lang?: string) {
  if (speakingId.value === id) stop()
  else speak(id, text, lang)
}

export function useVoiceOutput() {
  return { isSupported, speakingId, speak, stop, toggle }
}
