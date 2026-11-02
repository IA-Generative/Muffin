// Petites fonctions pures de la voix dans le chat (#517) : le format d'enregistrement, l'horloge, la langue d'un texte
// et la phrase qui dit où part la voix. Rien ici ne touche au navigateur : tout se teste sans lui.

// Les formats que les navigateurs savent enregistrer, du plus léger au plus courant : le serveur les accepte tous
// (webm, ogg, mp4), il vérifie leur contenu et non le type annoncé.
const RECORDER_TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4']

export function pickRecorderType(isTypeSupported: (type: string) => boolean): string | undefined {
  return RECORDER_TYPES.find((type) => isTypeSupported(type))
}

// 0:07, 12:03 — la durée écoulée d'un enregistrement.
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

const FRENCH = new Set(['le', 'la', 'les', 'des', 'une', 'un', 'est', 'et', 'que', 'qui', 'pour', 'dans', 'sur', 'avec', 'pas', 'vous', 'nous', 'ce', 'cette', 'du', 'au', 'aux', 'sont', 'été', 'peut', 'plus', 'ou', 'où'])
const ENGLISH = new Set(['the', 'and', 'is', 'are', 'of', 'to', 'in', 'that', 'for', 'with', 'not', 'you', 'this', 'these', 'from', 'be', 'was', 'were', 'can', 'will', 'or', 'it', 'on', 'as'])

// La langue d'un texte qu'on va lire, entre le français et l'anglais, d'après les mots courants : assez pour choisir une
// voix. `undefined` quand on ne peut pas trancher (texte court, mélangé, autre langue) : la voix par défaut est alors prise.
export function guessLanguage(text: string): 'fr' | 'en' | undefined {
  const words = text.toLowerCase().match(/[a-zàâçéèêëîïôûùüÿœ']+/g) ?? []
  let french = 0
  let english = 0
  for (const word of words) {
    if (FRENCH.has(word)) french += 1
    if (ENGLISH.has(word)) english += 1
  }
  if (french + english < 3 || french === english) return undefined
  return french > english ? 'fr' : 'en'
}

// Une réponse trop longue pour une seule demande de lecture est découpée en morceaux d'au plus `max` caractères, à la fin
// des phrases (et, à défaut, entre deux mots) : lus l'un après l'autre, sans couper une phrase au milieu quand on peut l'éviter.
export function chunkForSpeech(text: string, max: number): string[] {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (!clean) return []
  if (clean.length <= max) return [clean]
  const units: string[] = []
  for (const sentence of clean.split(/(?<=[.!?…])\s+/)) {
    if (sentence.length <= max) {
      units.push(sentence)
      continue
    }
    // Une phrase plus longue que le maximum est coupée entre deux mots ; un « mot » plus long (une adresse, une suite de
    // caractères) est coupé net.
    let line = ''
    for (const word of sentence.split(' ')) {
      for (let start = 0; start < word.length; start += max) {
        const part = word.slice(start, start + max)
        if (line && line.length + 1 + part.length > max) {
          units.push(line)
          line = part
        } else {
          line = line ? `${line} ${part}` : part
        }
      }
    }
    if (line) units.push(line)
  }
  const chunks: string[] = []
  let current = ''
  for (const unit of units) {
    if (current && current.length + 1 + unit.length > max) {
      chunks.push(current)
      current = unit
    } else {
      current = current ? `${current} ${unit}` : unit
    }
  }
  if (current) chunks.push(current)
  return chunks
}

export type VoiceDestination = 'hub' | 'service' | 'browser'

// Où part l'audio, dit à la personne avant qu'elle parle (la confidentialité de chaque moteur n'est pas la même).
export function dictationNotice(destination: VoiceDestination): string {
  if (destination === 'hub') {
    return 'Votre voix est enregistrée puis envoyée au service de modèles de l’organisation pour être transcrite. Rien n’est conservé.'
  }
  if (destination === 'service') {
    return 'Votre voix est enregistrée puis envoyée au service de transcription de l’organisation. Rien n’est conservé.'
  }
  return 'La dictée est faite par votre navigateur, qui peut envoyer l’audio à son fournisseur.'
}

export function speechNotice(destination: VoiceDestination): string {
  if (destination === 'hub') return 'La lecture est faite par le service de modèles de l’organisation : le texte lui est envoyé, rien n’est conservé.'
  if (destination === 'service') return 'La lecture est faite par le service vocal de l’organisation : le texte lui est envoyé, rien n’est conservé.'
  return 'La lecture est faite par la voix de votre navigateur.'
}

// Une erreur du serveur qui veut dire « ce moteur ne marche pas » (et non « votre enregistrement est refusé ») : la page
// retombe alors sur la dictée du navigateur pour la suite.
export function engineIsDown(status: number): boolean {
  return status === 404 || status >= 500
}
