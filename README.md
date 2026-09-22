# Muffin

Muffin est une plateforme de bases de connaissances documentaires avec un agent de recherche
conversationnel : on y importe des documents (upload ou URL scrapée) dans des **collections**,
chaque collection est indexée (chunking + embeddings + Meilisearch, recherche hybride), et un agent de recherche
(orchestré avec LangGraph) répond aux questions de l'utilisateur en allant chercher l'information
dans les collections auxquelles il a accès, avec citations vérifiables vers la source exacte
(document, page, chunk).

## Architecture

Cinq services applicatifs, plus l'infrastructure (Postgres, Redis, Meilisearch, Keycloak, RustFS,
SearXNG) :

| Service | Rôle | README |
|---|---|---|
| [`frontend/`](frontend/README.md) | Interface Vue 3 (DSFR) : chat, gestion des collections/documents, administration | [frontend/README.md](frontend/README.md) |
| [`backend/`](backend/README.md) | API FastAPI (BFF) : auth Keycloak, CRUD collections/documents/runs, seul service à parler à Postgres/Meilisearch/RustFS/au hub LLM | [backend/README.md](backend/README.md) |
| [`worker/document_process/`](worker/document_process/README.md) | Worker Celery : ingère un document (parsing, OCR, chunking, résumé, QA, embeddings) | [worker/document_process/README.md](worker/document_process/README.md) |
| [`worker/agent_execution/`](worker/agent_execution/README.md) | Worker Celery : exécute le graphe LangGraph de l'agent de recherche pour un run donné | [worker/agent_execution/README.md](worker/agent_execution/README.md) |
| [`worker/evaluation/`](worker/evaluation/README.md) | Worker Celery : évalue le retrieval d'une collection contre ses paires QA validées (issue #11) | [worker/evaluation/README.md](worker/evaluation/README.md) |

Les trois workers ne parlent jamais directement à Postgres/Meilisearch/RustFS : ils passent
uniquement par les endpoints internes du backend (`/internal/*`, authentifiés par un secret
partagé `WORKER_API_KEY`). Le backend reste le seul point d'accès aux données.

```
frontend ──HTTP──▶ backend ──┬──▶ Postgres
                              ├──▶ Meilisearch
                              ├──▶ RustFS (fichiers, screenshots de page)
                              ├──▶ Keycloak (auth)
                              └──▶ hub LLM (OpenAI-compatible)

backend ──Celery/Redis──▶ worker/document_process  (ingestion)
backend ──Celery/Redis──▶ worker/agent_execution    (recherche)
backend ──Celery/Redis──▶ worker/evaluation         (évaluation retrieval, queue dédiée)

les trois workers ──HTTP──▶ backend (/internal/*)
worker/agent_execution ──HTTP──▶ SearXNG (outil web_search, seule exception au point ci-dessus -
                                  jamais via le backend, aucune donnée utilisateur stockée là)
```

## Démarrer

```bash
make install   # uv, hooks git, dépendances backend
make up        # lance toute la stack en Docker (frontend, backend, workers, Postgres, Redis, Keycloak, Meilisearch, RustFS, SearXNG)
```

Pendant le développement, il est courant de lancer le frontend et/ou le backend hors Docker avec
rechargement à chaud, le reste restant en Docker :

```bash
make front     # frontend en hot-reload, http://localhost:5173
make back      # backend en hot-reload, http://localhost:8000/api/docs
```

`make help` liste toutes les commandes disponibles (install, lint, tests, migrations Alembic, ...).

## Fonctionnalités

Documentation illustrée (captures d'écran) des principales capacités de l'interface, par
fonctionnalité :

| Fonctionnalité | Doc |
|---|---|
| Collections : création, documents, chunks, Q/R, entités & relations, évaluation du retrieval | [docs/ui/collections/README.md](docs/ui/collections/README.md) |
| Chat : dictée vocale et lecture à voix haute des réponses | [docs/ui/chat/README.md](docs/ui/chat/README.md) |
| Suggestion de rangement automatique des fichiers uploadés dans le chat | [docs/ui/filing/README.md](docs/ui/filing/README.md) |
| Tutoriel de découverte affiché aux nouveaux utilisateurs | [docs/ui/onboarding/README.md](docs/ui/onboarding/README.md) |
| CGU : acceptation obligatoire et versionnée | [docs/ui/cgu/README.md](docs/ui/cgu/README.md) |
| Menu utilisateur : version de l'app, notes de version | [docs/ui/user-menu/README.md](docs/ui/user-menu/README.md) |
| Signalement de bug/idée/question, avec statut et réponse | [docs/ui/reports/README.md](docs/ui/reports/README.md) |
| Administration : paramètres globaux, prompts de l'agent, CGU, modèles, signalements | [docs/ui/admin/README.md](docs/ui/admin/README.md) |

## Documentation

- [docs/environment-variables.md](docs/environment-variables.md) — toutes les variables
  d'environnement, leur valeur par défaut et le(s) service(s) qui les consomment.
- [docs/research-agent-plan.md](docs/research-agent-plan.md) — architecture détaillée de l'agent
  de recherche (LangGraph, routing multi-collections, budgets d'exécution, grounding).
