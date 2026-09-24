<script setup lang="ts">
defineEmits<{ login: [] }>()

const features = [
  {
    title: 'Collections documentaires',
    description:
      "Regroupez vos documents dans des collections : upload direct ou import depuis une URL. Chaque collection est indexée automatiquement (découpage, résumé, embeddings, recherche hybride).",
  },
  {
    title: 'Agent de recherche conversationnel',
    description:
      "Posez vos questions en langage naturel : l'agent va chercher l'information dans les collections auxquelles vous avez accès et construit une réponse sourcée.",
  },
  {
    title: 'Citations vérifiables',
    description:
      "Chaque réponse renvoie vers la source exacte - document, page, extrait - pour vérifier l'information en un clic.",
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
      <h1 class="home__title">Retrouvez l'information dans vos documents, en conversant</h1>
      <p class="home__subtitle">
        Muffin est une plateforme de bases de connaissances documentaires : importez vos documents dans des
        collections, et interrogez-les grâce à un agent de recherche qui répond avec des citations vérifiables
        vers la source exacte.
      </p>
      <button type="button" class="fr-btn fr-btn--lg home__cta" @click="$emit('login')">Se connecter pour commencer</button>
    </main>

    <section class="home__features" aria-label="Fonctionnalités">
      <article v-for="feature in features" :key="feature.title" class="home__feature">
        <h2 class="home__feature-title">{{ feature.title }}</h2>
        <p class="home__feature-description">{{ feature.description }}</p>
      </article>
    </section>
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
  gap: 1.5rem;
  padding: 4rem 1.5rem 3rem;
  max-width: 46rem;
  margin: 0 auto;
}

.home__title {
  font-size: 2.25rem;
  line-height: 1.2;
  margin: 0;
}

.home__subtitle {
  font-size: 1.1rem;
  color: var(--text-mention-grey);
  margin: 0;
}

.home__features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  gap: 1.5rem;
  max-width: 64rem;
  width: 100%;
  margin: 0 auto;
  padding: 0 1.5rem 4rem;
  box-sizing: border-box;
}

.home__feature {
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-alt-grey);
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

@media (max-width: 40rem) {
  .home__header {
    padding: 1rem;
  }

  .home__hero {
    padding: 2.5rem 1rem 2rem;
  }

  .home__title {
    font-size: 1.65rem;
  }
}
</style>
