import { ref } from 'vue'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const PAGE_SIZE = 20

export interface Task {
  id: string
  taskName: string
  status: string
  documentId: string | null
  documentName: string | null
  collectionId: string | null
  collectionName: string | null
  parentId: string | null
  createdAt: string
}

interface TaskOut {
  id: string
  task_name: string
  status: string
  document_id: string | null
  document_name: string | null
  collection_id: string | null
  collection_name: string | null
  parent_id: string | null
  created_at: string
}

interface TaskPage {
  items: TaskOut[]
  total: number
  page: number
  page_size: number
}

function toTask(raw: TaskOut): Task {
  return {
    id: raw.id,
    taskName: raw.task_name,
    status: raw.status,
    documentId: raw.document_id,
    documentName: raw.document_name,
    collectionId: raw.collection_id,
    collectionName: raw.collection_name,
    parentId: raw.parent_id,
    createdAt: raw.created_at,
  }
}

const tasks = ref<Task[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)
const page = ref(1)
// Total number of runs (root tasks), not raw rows - a run's children always
// come back alongside their root regardless of page size, see backend's
// TaskService.list_tasks.
const pageCount = ref(1)
const totalTasks = ref(0)

// `quiet`: a refresh in the background (a running task's status), without the loading state.
async function fetchTasks({ quiet = false } = {}) {
  if (!quiet) isLoading.value = true
  error.value = null
  try {
    const response = await fetch(`${API_BASE_URL}/api/tasks?page=${page.value}&page_size=${PAGE_SIZE}`, {
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const body: TaskPage = await response.json()
    tasks.value = body.items.map(toTask)
    totalTasks.value = body.total
    pageCount.value = Math.max(1, Math.ceil(body.total / body.page_size))
  } catch {
    error.value = 'Impossible de récupérer les tâches.'
  } finally {
    isLoading.value = false
  }
}

async function revokeTask(id: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/api/tasks/${id}/revoke`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error(`${response.status}`)
    const task = toTask(await response.json())
    const index = tasks.value.findIndex((item) => item.id === id)
    if (index !== -1) tasks.value[index] = task
  } catch {
    error.value = 'Impossible de révoquer cette tâche.'
  }
}

export function useTasks() {
  return { tasks, isLoading, error, page, pageCount, totalTasks, fetchTasks, revokeTask }
}
