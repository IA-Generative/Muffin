<script setup lang="ts">
import { ref } from 'vue'
import type { GeneratedImage } from '../types/chat'

defineProps<{ images: GeneratedImage[] }>()

const downloading = ref<string | null>(null)
const failed = ref(false)

const EXTENSIONS: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }

// Télécharger passe par une requête avec les droits de la personne (cookie), puis un lien local : l'adresse de l'image
// est celle de l'API, d'une autre origine que la page, où l'attribut `download` d'un simple lien ne fait rien.
async function download(image: GeneratedImage) {
  downloading.value = image.id
  failed.value = false
  try {
    const response = await fetch(image.url, { credentials: 'include' })
    if (!response.ok) throw new Error(`${response.status}`)
    const link = document.createElement('a')
    link.href = URL.createObjectURL(await response.blob())
    link.download = `image-generee-par-ia-${image.id.slice(0, 8)}.${EXTENSIONS[image.contentType] ?? 'png'}`
    link.click()
    setTimeout(() => URL.revokeObjectURL(link.href), 1000)
  } catch {
    failed.value = true
  } finally {
    downloading.value = null
  }
}
</script>

<template>
  <div class="chat-images">
    <figure v-for="image in images" :key="image.id" class="chat-images__figure">
      <div class="chat-images__frame">
        <img
          :src="image.url"
          :width="image.width"
          :height="image.height"
          :alt="`Image générée par IA : ${image.prompt}`"
          class="chat-images__image"
          loading="lazy"
        />
        <span class="chat-images__badge">Image générée par IA</span>
      </div>
      <figcaption class="chat-images__caption">
        <span class="chat-images__prompt">{{ image.prompt }}</span>
        <button type="button" class="fr-btn fr-btn--sm fr-btn--tertiary" :disabled="downloading === image.id" @click="download(image)">
          {{ downloading === image.id ? 'Téléchargement…' : 'Télécharger' }}
        </button>
      </figcaption>
    </figure>
    <p v-if="failed" class="chat-images__error" role="alert">L’image n’a pas pu être téléchargée.</p>
  </div>
</template>

<style scoped>
.chat-images {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.chat-images__figure {
  margin: 0;
  max-width: 32rem;
}

.chat-images__frame {
  position: relative;
  display: inline-block;
  max-width: 100%;
}

.chat-images__image {
  display: block;
  max-width: 100%;
  height: auto;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-alt-grey);
}

.chat-images__badge {
  position: absolute;
  left: 0.5rem;
  bottom: 0.5rem;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  background: rgb(0 0 0 / 0.7);
  color: #fff;
  font-size: 0.75rem;
}

.chat-images__caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 0.375rem;
}

.chat-images__prompt {
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
  overflow-wrap: anywhere;
}

.chat-images__error {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-default-error);
}
</style>
