import type { Collection } from '../types/collection'

export const PATH_SEPARATOR = ' › '

// "RH › Congés" - a collection's ancestors as the current user can read them (#215).
export function formatPath(names: string[]): string {
  return names.join(PATH_SEPARATOR)
}

// "RH › Congés › Parental" - the collection itself included.
export function collectionPathLabel(collection: Pick<Collection, 'name' | 'path'>): string {
  return formatPath([...collection.path.map((item) => item.name), collection.name])
}
