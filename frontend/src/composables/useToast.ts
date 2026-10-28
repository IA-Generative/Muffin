import { ref } from 'vue'

export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  type: ToastType
  title: string
  description?: string
}

// Module-level state, like useCollections: every caller shares the same list, and the
// ToastHost mounted once in App.vue renders it wherever the toast was pushed from.
const toasts = ref<Toast[]>([])
let nextToastId = 1

// Exported directly besides the composable: callers that only push (useCollections) shouldn't
// have to destructure the whole API just to fire a notification.
export function pushToast(type: ToastType, title: string, description?: string, durationMs = 6000): number {
  const id = nextToastId++
  toasts.value = [...toasts.value, { id, type, title, description }]
  // 0 disables auto-dismiss (the toast then lives until its close button is used).
  if (durationMs > 0) setTimeout(() => dismissToast(id), durationMs)
  return id
}

function dismissToast(id: number) {
  toasts.value = toasts.value.filter((toast) => toast.id !== id)
}

export function useToast() {
  return { toasts, pushToast, dismissToast }
}
