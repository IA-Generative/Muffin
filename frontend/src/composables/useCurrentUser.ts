import { ref } from 'vue'
import type { User } from '../types/user'

// Mock jusqu'au branchement de l'auth réelle.
const user = ref<User>({ name: 'Michou', email: 'michou@example.com' })

export function useCurrentUser() {
  return { user }
}
