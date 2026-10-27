// How the cost of the worker tasks reads: duration, memory and energy, in French.

const number = (value: number, digits: number) =>
  value.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

export function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${number(seconds, seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  if (seconds < 3600)
    return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
  return `${Math.floor(seconds / 3600)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "–";
  if (bytes < 1e9) return `${number(bytes / 1e6, bytes < 1e8 ? 1 : 0)} Mo`;
  return `${number(bytes / 1e9, 2)} Go`;
}

export function formatEnergy(wattHours: number): string {
  if (wattHours <= 0) return "0 Wh";
  if (wattHours < 0.01) return "< 0,01 Wh";
  if (wattHours < 1000)
    return `${number(wattHours, wattHours < 10 ? 2 : 1)} Wh`;
  return `${number(wattHours / 1000, 2)} kWh`;
}

// Orders of magnitude to picture an energy by: a LED bulb and an alkaline AA battery (1,5 V x 2,4 Ah).
export const LED_BULB_WATTS = 10;
export const AA_BATTERY_WH = 3.6;

export function bulbSeconds(wattHours: number): number {
  return (wattHours * 3600) / LED_BULB_WATTS;
}

export function batteryCount(wattHours: number): number {
  return wattHours / AA_BATTERY_WH;
}
