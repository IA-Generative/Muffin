import { computed, ref } from 'vue'
import type { User } from '../types/user'

// The browser talks to the backend directly (not through the Vite/nginx
// origin): the BFF session cookie is scoped to this origin, and CORS on the
// backend explicitly allows it (see KeycloakSettings.FRONTEND_URL).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface AuthMe {
  user_id: string
  email: string
  first_name: string
  last_name: string
  roles: string[]
  is_admin: boolean
}

function toUser(me: AuthMe): User {
  const name = [me.first_name, me.last_name].filter(Boolean).join(' ')
  return { name: name || me.email || me.user_id, email: me.email, isAdmin: me.is_admin }
}

// Module-level singleton: the whole app shares one auth state.
const user = ref<User | null>(null)
const isLoading = ref(true)
const isAuthenticated = computed(() => user.value !== null)

async function fetchMe() {
  isLoading.value = true
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/me`, { credentials: 'include' })
    user.value = response.ok ? toUser(await response.json()) : null
  } catch {
    user.value = null
  } finally {
    isLoading.value = false
  }
}

function login(redirect: string = window.location.pathname) {
  // When API_BASE_URL is empty (same-origin, ingress-routed prod), fall back
  // to window.location.origin so `new URL` gets a valid base. In dev,
  // API_BASE_URL is an absolute URL (http://localhost:8000) and is used as-is.
  const url = new URL(`${API_BASE_URL}/api/auth/login`, window.location.origin)
  url.searchParams.set('redirect', redirect)
  window.location.href = url.toString()
}

async function logout() {
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
  user.value = null
  const { redirectUrl } = await response.json()
  window.location.href = redirectUrl
}

fetchMe()

export function useCurrentUser() {
  return { user, isAuthenticated, isLoading, login, logout, refresh: fetchMe }
}
