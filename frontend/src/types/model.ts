export interface ChatModel {
  id: string
}

// Valeur du modèle d'un message qui laisse l'agent choisir selon la difficulté de la demande.
export const AUTO_MODEL_ID = 'auto'

// Ce qu'un modèle sait faire, calculé par le backend (jamais modifiable) : affiché en étiquettes.
export type ModelCapability =
  | 'chat'
  | 'vision'
  | 'embeddings'
  | 'image_generation'
  | 'speech_to_text'
  | 'text_to_speech'

export interface ModelProfile {
  id: string
  capabilities: ModelCapability[]
  score: number
  description: string | null
  auto_enabled: boolean
  described: boolean
}
