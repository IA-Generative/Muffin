# frontend

Interface Vue 3 de Muffin (design system DSFR - `@gouvfr/dsfr`/`@gouvminint/vue-dsfr`) : chat de
recherche, gestion des collections/documents, suivi des tâches d'ingestion, administration.

Parle uniquement au backend (`VITE_API_BASE_URL`, voir `docs/environment-variables.md` à la racine
du repo) - jamais directement à Postgres/Qdrant/Keycloak.

## Pages (`src/router/index.ts`)

| Route | Vue | Rôle |
|---|---|---|
| `/`, `/c/:id` | `ChatView.vue` | Chat de recherche : composer, réponses avec citations, panneau Sources (document/tool), détail d'exécution |
| `/collections` | `CollectionsView.vue` | Liste des collections de l'utilisateur |
| `/collections/:id` | `CollectionDetailView.vue` | Détail d'une collection : documents, tags, paramètres de chunking/embedding, QA, entités/relations |
| `/collections/:id/documents/:documentId` | `DocumentDetailModal.vue` (deep-link) | Détail d'un document : résumé, pages, QA associées |
| `/tasks` | `TasksView.vue` | Suivi des tâches Celery d'ingestion en cours/passées |
| `/admin` | `AdminSettingsView.vue` | Réglages globaux (modèles LLM disponibles, etc.) |

## Structure

```
src/
  components/    composants Vue (une vue = un fichier *View.vue, le reste = composants réutilisés)
  composables/   logique/état partagé (use*.ts) - un composable par ressource API
                 (useChat, useCollections, useTasks, useModels, useCurrentUser, ...)
  router/        définition des routes (vue-router)
  types/         types TypeScript partagés (formes camelCase, alors que l'API répond en snake_case -
                 chaque composable convertit à la frontière, voir toCollection/toChat etc.)
```

Chaque composable gère lui-même son état réactif partagé (pas de Pinia/Vuex) et ses appels
`fetch` vers l'API - voir par exemple `useChat.ts` (création/suivi de run, polling des événements)
ou `useCollections.ts` (CRUD collections, cache local des collections chargées).

## Développer

```bash
make front              # ou : cd frontend && npm run dev  -> http://localhost:5173
npm run typecheck        # vue-tsc --noEmit (le vrai gate CI, pas de linter séparé)
npm run build             # build de prod (utilisé par le Dockerfile)
npm run screenshot -- <nom> [chemin] [url]   # capture d'écran Playwright pour la doc
```

Le frontend est servi par nginx en prod (voir `Dockerfile`) ; en Docker Compose local il tourne
sous le service `frontend` sur le port hôte `8081` (le port `8080` est déjà pris par Keycloak).
