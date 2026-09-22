import { ref } from 'vue'
import type { Report, ReportStatus, ReportType } from './useReports'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface AdminReport extends Report {
  userDisplay: string
  respondedBy: string | null
}

interface ReportAdminOut {
  id: string
  type: ReportType
  title: string
  description: string
  status: ReportStatus
  screenshot_url: string | null
  admin_response: string | null
  created_at: string
  updated_at: string
  user_display: string
  responded_by: string | null
}

function toAdminReport(raw: ReportAdminOut): AdminReport {
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
    userDisplay: raw.user_display,
    respondedBy: raw.responded_by,
  }
}

const reports = ref<AdminReport[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchReports(status?: ReportStatus, type?: ReportType) {
  isLoading.value = true
  error.value = null
  try {
    const params = new URLSearchParams()
    if (status) params.set('status_filter', status)
    if (type) params.set('type_filter', type)
    const query = params.toString()
    const response = await fetch(`${API_BASE_URL}/api/admin/reports${query ? `?${query}` : ''}`, {
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    reports.value = (await response.json()).map(toAdminReport)
  } catch {
    error.value = 'Impossible de récupérer les signalements.'
  } finally {
    isLoading.value = false
  }
}

async function updateReport(id: string, status: ReportStatus, adminResponse?: string): Promise<boolean> {
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/admin/reports/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, admin_response: adminResponse }),
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const updated = toAdminReport(await response.json())
    reports.value = reports.value.map((report) => (report.id === updated.id ? updated : report))
    return true
  } catch {
    error.value = 'Impossible de mettre à jour ce signalement.'
    return false
  }
}

export function useReportsAdmin() {
  return { reports, isLoading, error, fetchReports, updateReport }
}
