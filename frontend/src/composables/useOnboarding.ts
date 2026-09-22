import { ref } from 'vue'

// Per-viewer convenience only, never read back by anything else - same reasoning as
// ChatSidebar.vue's COLLAPSE_STORAGE_KEY (§135): a preference tied to this browser, not
// something the backend needs to know about or sync across devices.
const DISMISSED_STORAGE_KEY = 'muffin-onboarding-dismissed'

const showTutorial = ref(false)
const dismissedForever = ref(false)
try {
  dismissedForever.value = localStorage.getItem(DISMISSED_STORAGE_KEY) === 'true'
} catch {
  // Private browsing / storage blocked - just default to "not dismissed", the tutorial shows
  // once per session in that case rather than never at all.
}

function openTutorial() {
  showTutorial.value = true
}

// Just hides it for now (e.g. the "✕" close, or reaching the end without hitting "Ne plus
// afficher") - it reappears on the next reload unless dismissForever() was called instead.
function closeTutorial() {
  showTutorial.value = false
}

function dismissForever() {
  dismissedForever.value = true
  showTutorial.value = false
  try {
    localStorage.setItem(DISMISSED_STORAGE_KEY, 'true')
  } catch {
    // Ignored - worst case it shows again next session, not worth surfacing an error for.
  }
}

export function useOnboarding() {
  return { showTutorial, dismissedForever, openTutorial, closeTutorial, dismissForever }
}
