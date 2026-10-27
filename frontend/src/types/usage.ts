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

export interface ExecutionSums {
  count: number
  durationSeconds: number
  cpuSeconds: number
  // The most memory one execution held; 0 for an agent step, which has none of its own.
  peakRssBytes: number
  // Estimated from the CPU time and memory, never measured.
  energyWh: number
}

export interface ExecutionStep extends ExecutionSums {
  // A worker "task", or a "node": a step of the agent, run inside a task and so not added to the totals.
  kind: 'task' | 'node'
  step: string
}

export interface ExecutionDay extends ExecutionSums {
  day: string
}

export interface Execution {
  totals: ExecutionSums
  byStep: ExecutionStep[]
  byDay: ExecutionDay[]
  assumptions: { wattsPerCore: number; wattsPerGb: number; pue: number }
}

export interface Usage {
  days: number
  totals: UsageSums
  byStep: StepUsage[]
  byDay: DayUsage[]
  byModel: ModelUsage[]
  // Administrators only - always empty on a user's own report.
  byUser: UserUsage[]
  execution: Execution
}
