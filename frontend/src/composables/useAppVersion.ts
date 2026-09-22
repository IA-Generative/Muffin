import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface HealthReport {
  version: string
}

// Module-level singleton, same reasoning as useCurrentUser's `user` - fetched once for the
// whole app, not once per user-menu open. Reuses GET /health (§128) rather than a dedicated
// endpoint - the version is already in that response, no need for a second round-trip.
const version = ref<string | null>(null)

async function fetchAppVersion() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, { credentials: 'include' })
    // A 503 (an unhealthy dependency) still carries a body with the version - read it either
    // way, this display doesn't care about overall health, just what's running.
    const body: HealthReport = await response.json()
    version.value = body.version
  } catch {
    // Best-effort: the version label just stays hidden, not worth surfacing an error for.
  }
}

fetchAppVersion()

export function useAppVersion() {
  return { version }
}
