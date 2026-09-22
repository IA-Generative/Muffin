import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type ReportType = 'bug' | 'idea' | 'question'
export type ReportStatus = 'new' | 'in_progress' | 'resolved' | 'wont_fix'

export interface Report {
  id: string
  type: ReportType
  title: string
  description: string
  status: ReportStatus
  screenshotUrl: string | null
  adminResponse: string | null
  createdAt: string
  updatedAt: string
}

interface ReportOut {
  id: string
  type: ReportType
  title: string
  description: string
  status: ReportStatus
  screenshot_url: string | null
  admin_response: string | null
  created_at: string
  updated_at: string
}

function toReport(raw: ReportOut): Report {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    description: raw.description,
    status: raw.status,
    screenshotUrl: raw.screenshot_url,
    adminResponse: raw.admin_response,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  }
}

// Module-level singleton, same reasoning as useCgu's `status` - shared across the app (the user
// menu button and the modal don't need to be the same component instance).
const myReports = ref<Report[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchMyReports() {
  isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/reports`, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    myReports.value = (await response.json()).map(toReport)
  } catch {
    error.value = 'Impossible de récupérer vos signalements.'
  } finally {
    isLoading.value = false
  }
}

async function createReport(
  type: ReportType,
  title: string,
  description: string,
  screenshot: Blob | null,
): Promise<boolean> {
  error.value = null
  try {
    const formData = new FormData()
    formData.append('type', type)
    formData.append('title', title)
    formData.append('description', description)
    if (screenshot) formData.append('screenshot', screenshot, 'screenshot.png')
    const response = await fetch(`${API_BASE_URL}/api/reports`, {
      method: 'POST',
      credentials: 'include',
      body: formData,
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const created = toReport(await response.json())
    myReports.value = [created, ...myReports.value]
    return true
  } catch {
    error.value = "Impossible d'envoyer votre signalement - veuillez réessayer."
    return false
  }
}

export function useReports() {
  return { myReports, isLoading, error, fetchMyReports, createReport }
}
