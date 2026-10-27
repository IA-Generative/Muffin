// How the cost of the worker tasks reads: duration, memory and energy, in French.

const number = (value: number, digits: number) =>
  value.toLocaleString('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

export function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${number(seconds, seconds < 10 ? 1 : 0)} s`
  const minutes = Math.floor(seconds / 60)
  if (seconds < 3600) return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, '0')} s`
  return `${Math.floor(seconds / 3600)} h ${String(minutes % 60).padStart(2, '0')} min`
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '–'
  if (bytes < 1e9) return `${number(bytes / 1e6, bytes < 1e8 ? 1 : 0)} Mo`
  return `${number(bytes / 1e9, 2)} Go`
}

export function formatEnergy(wattHours: number): string {
  if (wattHours <= 0) return '0 Wh'
  if (wattHours < 0.01) return '< 0,01 Wh'
  if (wattHours < 1000) return `${number(wattHours, wattHours < 10 ? 2 : 1)} Wh`
  return `${number(wattHours / 1000, 2)} kWh`
}

// Orders of magnitude to picture an energy by: a LED bulb, and the battery of a smartphone (about 3,8 V x 3,4 Ah).
export const LED_BULB_WATTS = 10
export const PHONE_BATTERY_WH = 13

export function bulbSeconds(wattHours: number): number {
  return (wattHours * 3600) / LED_BULB_WATTS
}

export function phoneCharges(wattHours: number): number {
  return wattHours / PHONE_BATTERY_WH
}

// Past `max` items (bottles, batteries), the full ones are folded into a count and the last `max` are drawn:
// the one still filling is always among them, only full ones are ever hidden.
export function foldFull(total: number, max: number): { folded: number; shown: number } {
  const folded = Math.max(0, total - max)
  return { folded, shown: total - folded }
}
