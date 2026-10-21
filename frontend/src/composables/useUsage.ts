import { ref, watch, type Ref } from 'vue'
import type { Usage, UsageSums } from '../types/usage'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

interface SumsOut {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  calls: number
}

interface UsageOut {
  days: number
  totals: SumsOut
  by_step: (SumsOut & { step: string })[]
  by_day: (SumsOut & { day: string })[]
  by_model: (SumsOut & { model: string })[]
  by_user: (SumsOut & { user_id: string | null; display: string | null })[]
}

function toSums(raw: SumsOut): UsageSums {
  return {
    inputTokens: raw.input_tokens,
    outputTokens: raw.output_tokens,
    totalTokens: raw.total_tokens,
    calls: raw.calls,
  }
}

function toUsage(raw: UsageOut): Usage {
  return {
    days: raw.days,
    totals: toSums(raw.totals),
    byStep: raw.by_step.map((row) => ({ step: row.step, ...toSums(row) })),
    byDay: raw.by_day.map((row) => ({ day: row.day, ...toSums(row) })),
    byModel: raw.by_model.map((row) => ({ model: row.model, ...toSums(row) })),
    byUser: raw.by_user.map((row) => ({ userId: row.user_id, display: row.display, ...toSums(row) })),
  }
}

// `admin`: everyone's consumption (GET /api/admin/usage), narrowed to `userId` when one is set.
export function useUsage(days: Ref<number>, options: { admin?: boolean; userId?: Ref<string | null> } = {}) {
  const usage = ref<Usage | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function load() {
    isLoading.value = true
    error.value = null
    const params = new URLSearchParams({ days: String(days.value) })
    if (options.admin && options.userId?.value) params.set('user_id', options.userId.value)
    try {
      const path = options.admin ? '/api/admin/usage' : '/api/usage/me'
      const response = await fetch(`${API_BASE_URL}${path}?${params}`, { credentials: 'include' })
      if (!response.ok) throw new Error(`${response.status}`)
      usage.value = toUsage(await response.json())
    } catch {
      error.value = 'Impossible de récupérer la consommation.'
    } finally {
      isLoading.value = false
    }
  }

  watch([days, () => options.userId?.value], load, { immediate: true })

  return { usage, isLoading, error, reload: load }
}
