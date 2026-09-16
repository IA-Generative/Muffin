import { ref, watch } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'muffin-theme'

function readStored(): ThemeMode {
  const stored = localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

function systemPrefersDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolve(mode: ThemeMode): 'light' | 'dark' {
  return mode === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : mode
}

// Module-level singleton: every component importing this composable shares
// the same reactive state instead of each holding its own copy.
const mode = ref<ThemeMode>(readStored())

function apply() {
  document.documentElement.setAttribute('data-fr-theme', resolve(mode.value))
}

apply()
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (mode.value === 'system') apply()
})

watch(mode, (value) => {
  localStorage.setItem(STORAGE_KEY, value)
  apply()
})

export function useTheme() {
  return { mode }
}
