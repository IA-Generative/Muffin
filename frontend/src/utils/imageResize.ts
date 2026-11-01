// Les images jointes à un message (#512) : ce que le navigateur en fait avant de les envoyer. Une capture d'écran de 4000
// pixels coûte des jetons au modèle qui la lit, sans qu'il y voie mieux : on la réduit ici, et le serveur ne garde que ce
// qui reste dans ses bornes.

export const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp']
// Le plus grand côté envoyé (pixels).
export const MAX_SIDE = 2048

export function isAcceptedImage(file: { type: string }): boolean {
  return ACCEPTED_TYPES.includes(file.type)
}

// Les dimensions d'une image qui tient dans un carré de `max` pixels de côté : proportions gardées, jamais agrandie.
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  const longest = Math.max(width, height)
  if (longest <= max) return { width, height }
  const ratio = max / longest
  return { width: Math.max(1, Math.round(width * ratio)), height: Math.max(1, Math.round(height * ratio)) }
}

// Les images d'un presse-papiers ou d'un glisser-déposer, parmi ce qu'il contient d'autre.
export function imagesOf(files: Iterable<File> | ArrayLike<File> | null | undefined): File[] {
  return files ? Array.from(files).filter(isAcceptedImage) : []
}

function encode(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality))
}

// Le fichier à envoyer : l'image elle-même quand elle est déjà dans les bornes, sinon une copie réduite - dans son type
// (une capture de texte reste nette en PNG), puis en JPEG si elle pèse encore trop. Une image que le navigateur ne sait
// pas lire est rendue telle quelle : c'est le serveur qui la refuse, avec ses mots.
export async function prepareImage(file: File, maxBytes: number): Promise<File> {
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    return file
  }
  try {
    const target = fitWithin(bitmap.width, bitmap.height, MAX_SIDE)
    const resized = target.width !== bitmap.width || target.height !== bitmap.height
    if (!resized && file.size <= maxBytes) return file
    const canvas = document.createElement('canvas')
    canvas.width = target.width
    canvas.height = target.height
    const context = canvas.getContext('2d')
    if (!context) return file
    context.drawImage(bitmap, 0, 0, target.width, target.height)
    const base = file.name.replace(/\.[^.]+$/, '') || 'image'
    const same = await encode(canvas, file.type)
    if (same && same.size <= maxBytes) return new File([same], file.name, { type: same.type })
    // Un JPEG n'a pas de transparence : le fond est blanc plutôt que noir.
    context.globalCompositeOperation = 'destination-over'
    context.fillStyle = '#fff'
    context.fillRect(0, 0, target.width, target.height)
    for (const quality of [0.9, 0.8, 0.65]) {
      const jpeg = await encode(canvas, 'image/jpeg', quality)
      if (jpeg && jpeg.size <= maxBytes) return new File([jpeg], `${base}.jpg`, { type: 'image/jpeg' })
    }
    return file
  } finally {
    bitmap.close()
  }
}
