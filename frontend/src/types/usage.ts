export interface UsageSums {
  inputTokens: number
  outputTokens: number
  totalTokens: number
  calls: number
}

export interface StepUsage extends UsageSums {
  step: string
}

export interface DayUsage extends UsageSums {
  day: string
}

export interface ModelUsage extends UsageSums {
  model: string
}

export interface UserUsage extends UsageSums {
  // null for the calls that couldn't be tied to anyone (e.g. a discussion score).
  userId: string | null
  display: string | null
}

export interface Usage {
  days: number
  totals: UsageSums
  byStep: StepUsage[]
  byDay: DayUsage[]
  byModel: ModelUsage[]
  // Administrators only - always empty on a user's own report.
  byUser: UserUsage[]
}
