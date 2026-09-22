<script setup lang="ts">
import { ref } from 'vue'
import { useOnboarding } from '../composables/useOnboarding'

const { closeTutorial, dismissForever } = useOnboarding()

interface Step {
  icon: string
  title: string
  description: string
}

// §135: a truthful walkthrough of what's actually in the app today, not a generic placeholder -
// each step maps to a real feature (§88-92 conv-files, §108/#111 a11y, the collection picker's
// web-search toggle) so a new user leaves knowing where to find each one, not just that they
// exist.
const steps: Step[] = [
  {
    icon: '👋',
    title: 'Bienvenue sur Muffin',
    description:
      "Muffin est un assistant de recherche documentaire : posez une question, il y répond en s'appuyant sur le contenu de vos documents et cite ses sources - jamais une réponse inventée sans preuve.",
  },
  {
    icon: '📁',
    title: 'Vos collections',
    description:
      "Regroupez vos documents par thème dans des collections (menu « Collections »). Chaque collection peut être privée, partagée avec des personnes ou des groupes précis, ou publique.",
  },
  {
    icon: '💬',
    title: 'Posez votre question',
    description:
      "Épinglez une ou plusieurs collections avec le bouton « + » du champ de saisie, puis écrivez votre question. Cliquez sur les numéros de citation dans la réponse pour voir l'extrait exact d'où vient chaque information.",
  },
  {
    icon: '📎',
    title: 'Joindre un fichier directement dans la conversation',
    description:
      "Pas besoin de créer une collection pour un fichier ponctuel : le trombone du champ de saisie l'envoie directement dans la conversation. Muffin vous proposera ensuite, s'il trouve une correspondance, de le ranger dans l'une de vos collections.",
  },
  {
    icon: '🌐',
    title: 'Recherche web',
    description:
      "Quand vos documents ne suffisent pas, activez la recherche web depuis le même bouton « + » - désactivée par défaut, à activer volontairement message par message.",
  },
  {
    icon: '🎙️',
    title: 'Accessibilité',
    description:
      "Dictez votre message au micro (raccourci Alt+Maj+V) ou faites lire la dernière réponse à voix haute (Alt+Maj+L) - utile depuis n'importe où dans l'app, pas seulement le champ de saisie.",
  },
  {
    icon: '🔁',
    title: 'Pour revoir ce tutoriel',
    description:
      "Ce guide reste accessible à tout moment depuis le menu utilisateur (en bas à gauche), à côté des Conditions d'utilisation et de la version de l'app.",
  },
]

const stepIndex = ref(0)
const isLastStep = () => stepIndex.value === steps.length - 1

function next() {
  if (isLastStep()) dismissForever()
  else stepIndex.value += 1
}

function previous() {
  if (stepIndex.value > 0) stepIndex.value -= 1
}
</script>

<template>
  <div class="onboarding-overlay" @click.self="closeTutorial">
    <div class="onboarding" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
      <button type="button" class="onboarding__close" aria-label="Fermer" @click="closeTutorial">✕</button>

      <div class="onboarding__icon" aria-hidden="true">{{ steps[stepIndex].icon }}</div>
      <h2 id="onboarding-title" class="onboarding__title">{{ steps[stepIndex].title }}</h2>
      <p class="onboarding__description">{{ steps[stepIndex].description }}</p>

      <div class="onboarding__dots">
        <button
          v-for="(step, index) in steps"
          :key="step.title"
          type="button"
          class="onboarding__dot"
          :class="{ 'onboarding__dot--active': index === stepIndex }"
          :aria-label="`Aller à l'étape ${index + 1} : ${step.title}`"
          :aria-current="index === stepIndex"
          @click="stepIndex = index"
        />
      </div>

      <footer class="onboarding__footer">
        <button type="button" class="fr-btn fr-btn--tertiary" @click="dismissForever">Ne plus afficher</button>
        <div class="onboarding__nav">
          <button
            type="button"
            class="fr-btn fr-btn--secondary"
            :disabled="stepIndex === 0"
            @click="previous"
          >
            Précédent
          </button>
          <button type="button" class="fr-btn" @click="next">
            {{ isLastStep() ? 'Terminer' : 'Suivant' }}
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.onboarding-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 1.5rem;
}

.onboarding {
  position: relative;
  width: 100%;
  max-width: 28rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.75rem;
  box-sizing: border-box;
  padding: 2rem 1.75rem 1.5rem;
  text-align: center;
}

.onboarding__close {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  border: none;
  background: transparent;
  color: var(--text-mention-grey);
  cursor: pointer;
  font-size: 1rem;
}

.onboarding__icon {
  font-size: 2.5rem;
  line-height: 1;
  margin-bottom: 0.75rem;
}

.onboarding__title {
  font-size: 1.1875rem;
  margin: 0 0 0.75rem;
}

.onboarding__description {
  color: var(--text-mention-grey);
  font-size: 0.9375rem;
  line-height: 1.5;
  margin: 0 0 1.25rem;
  min-height: 5.5rem;
}

.onboarding__dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  margin-bottom: 1.5rem;
}

.onboarding__dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 999px;
  border: none;
  padding: 0;
  background: var(--background-alt-grey-hover);
  cursor: pointer;
}

.onboarding__dot--active {
  background: var(--background-action-high-blue-france);
}

.onboarding__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.onboarding__nav {
  display: flex;
  gap: 0.5rem;
  margin-left: auto;
}
</style>
