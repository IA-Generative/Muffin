<script setup lang="ts">
defineEmits<{ login: [] }>()

const features = [
  {
    icon: 'fr-icon-folder-2-line',
    title: 'Collections documentaires',
    description:
      "Regroupez vos documents dans des collections : upload direct ou import depuis une URL. Chaque collection est indexée automatiquement (découpage, résumé, embeddings, recherche hybride).",
  },
  {
    icon: 'fr-icon-chat-3-line',
    title: 'Agent de recherche conversationnel',
    description:
      "Posez vos questions en langage naturel : l'agent va chercher l'information dans les collections auxquelles vous avez accès et construit une réponse sourcée.",
  },
  {
    icon: 'fr-icon-quote-line',
    title: 'Citations vérifiables',
    description:
      "Chaque réponse renvoie vers la source exacte - document, page, extrait - pour vérifier l'information en un clic.",
  },
  {
    icon: 'fr-icon-shield-line',
    title: 'Accès maîtrisé',
    description:
      "Chaque collection dispose de ses propres droits d'accès : vous ne voyez et n'interrogez que les documents auxquels vous êtes autorisé.",
  },
  {
    icon: 'fr-icon-upload-2-line',
    title: 'Import flexible',
    description:
      "Déposez vos fichiers (PDF, Office, texte...) ou importez-les directement depuis une URL. Le traitement et l'indexation se font automatiquement.",
  },
  {
    icon: 'fr-icon-file-text-line',
    title: 'Suivi qualité',
    description:
      "Un tableau de bord qualité et un espace de revue vous permettent de suivre le classement et la fiabilité des réponses fournies par l'agent.",
  },
]

const steps = [
  {
    title: 'Importez vos documents',
    description: "Créez une collection et ajoutez vos fichiers par upload ou par URL.",
  },
  {
    title: "Laissez Muffin les indexer",
    description: 'Découpage, résumé et embeddings sont générés automatiquement pour préparer la recherche.',
  },
  {
    title: 'Posez vos questions',
    description: "L'agent conversationnel répond en citant précisément ses sources.",
  },
]
</script>

<template>
  <div class="home">
    <header class="home__header">
      <p class="fr-logo home__logo">Muffin</p>
      <button type="button" class="fr-btn home__header-cta" @click="$emit('login')">Se connecter</button>
    </header>

    <main class="home__hero">
      <p class="fr-badge fr-badge--blue-cumulus home__badge">Bases de connaissances documentaires</p>
      <h1 class="home__title">Retrouvez l'information dans vos documents, en conversant</h1>
      <p class="home__tagline">Muffin&nbsp;: cuisiner vos connaissances pour bien vous les servir</p>
      <p class="home__subtitle">
        Muffin est une plateforme de bases de connaissances documentaires : importez vos documents dans des
        collections, et interrogez-les grâce à un agent de recherche qui répond avec des citations vérifiables
        vers la source exacte.
      </p>
      <div class="home__hero-actions">
        <button type="button" class="fr-btn fr-btn--lg home__cta" @click="$emit('login')">
          Se connecter pour commencer
        </button>
      </div>
    </main>

    <section class="home__steps" aria-label="Comment ça marche">
      <h2 class="home__section-title">Comment ça marche</h2>
      <ol class="home__steps-list">
        <li v-for="(step, index) in steps" :key="step.title" class="home__step">
          <span class="home__step-number">{{ index + 1 }}</span>
          <h3 class="home__step-title">{{ step.title }}</h3>
          <p class="home__step-description">{{ step.description }}</p>
        </li>
      </ol>
    </section>

    <section class="home__features" aria-label="Fonctionnalités">
      <h2 class="home__section-title">Fonctionnalités</h2>
      <div class="home__features-grid">
        <article v-for="feature in features" :key="feature.title" class="home__feature">
          <span class="home__feature-icon fr-icon fr-icon--lg" :class="feature.icon" aria-hidden="true"></span>
          <h3 class="home__feature-title">{{ feature.title }}</h3>
          <p class="home__feature-description">{{ feature.description }}</p>
        </article>
      </div>
    </section>

    <footer class="home__footer">
      <div class="home__footer-cta">
        <h2 class="home__footer-title">Prêt à explorer vos documents autrement ?</h2>
        <button type="button" class="fr-btn fr-btn--lg" @click="$emit('login')">Se connecter</button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  width: 100%;
  overflow-y: auto;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
}

.home__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.25rem 2rem;
  border-bottom: 1px solid var(--border-default-grey);
  position: sticky;
  top: 0;
  background: var(--background-default-grey);
  z-index: 10;
}

.home__logo {
  font-size: 1.2rem;
  margin: 0;
}

.home__hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 1.25rem;
  padding: 4.5rem 1.5rem 3.5rem;
  max-width: 48rem;
  margin: 0 auto;
}

.home__badge {
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.home__title {
  font-size: 2.5rem;
  line-height: 1.15;
  margin: 0;
}

.home__tagline {
  font-size: 1.15rem;
  font-style: italic;
  font-weight: 500;
  color: var(--text-action-high-blue-france, var(--text-default-grey));
  margin: 0;
}

.home__subtitle {
  font-size: 1.15rem;
  color: var(--text-mention-grey);
  margin: 0;
  max-width: 42rem;
}

.home__hero-actions {
  margin-top: 0.5rem;
}

.home__section-title {
  font-size: 1.6rem;
  text-align: center;
  margin: 0 0 2rem;
}

.home__steps {
  padding: 3rem 1.5rem;
  background: var(--background-alt-grey);
}

.home__steps-list {
  list-style: none;
  margin: 0 auto;
  padding: 0;
  max-width: 64rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 2rem;
}

.home__step {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
}

.home__step-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
  font-weight: bold;
}

.home__step-title {
  font-size: 1.1rem;
  margin: 0;
}

.home__step-description {
  margin: 0;
  color: var(--text-mention-grey);
}

.home__features {
  padding: 4rem 1.5rem;
  max-width: 72rem;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.home__features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr));
  gap: 1.5rem;
}

.home__feature {
  padding: 1.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
  background: var(--background-default-grey);
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}

.home__feature:hover {
  box-shadow: 0 0.25rem 0.75rem rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.home__feature-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.5rem;
  background: var(--background-alt-blue-france, var(--background-alt-grey));
  color: var(--text-action-high-blue-france, var(--text-default-grey));
  font-size: 1.4rem;
  margin-bottom: 1rem;
}

.home__feature-title {
  font-size: 1.1rem;
  line-height: 1.3;
  margin: 0 0 0.5rem;
}

.home__feature-description {
  margin: 0;
  color: var(--text-mention-grey);
}

.home__footer {
  padding: 4rem 1.5rem;
  border-top: 1px solid var(--border-default-grey);
  background: var(--background-alt-grey);
}

.home__footer-cta {
  max-width: 40rem;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1.5rem;
  text-align: center;
}

.home__footer-title {
  font-size: 1.5rem;
  margin: 0;
}

@media (max-width: 40rem) {
  .home__header {
    padding: 1rem;
  }

  .home__hero {
    padding: 3rem 1rem 2.5rem;
  }

  .home__title {
    font-size: 1.8rem;
  }

  .home__steps,
  .home__features,
  .home__footer {
    padding: 2.5rem 1rem;
  }
}
</style>
