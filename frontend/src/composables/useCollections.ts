import { ref } from 'vue'
import type { Collection } from '../types/chat'

// Mock jusqu'au branchement du backend.
const collections = ref<Collection[]>([
  {
    id: 'c1',
    name: 'Projets',
    description: 'Notes et documents liés aux projets en cours.',
    documentCount: 4,
  },
  {
    id: 'c2',
    name: 'Notes',
    description: 'Notes personnelles diverses.',
    documentCount: 12,
  },
])

function createCollection() {
  const id = crypto.randomUUID()
  collections.value.unshift({ id, name: 'Nouvelle collection', description: '', documentCount: 0 })
}

function openCollection(id: string) {
  console.log('Collection ouverte :', id)
}

export function useCollections() {
  return { collections, createCollection, openCollection }
}
