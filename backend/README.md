# backend

API FastAPI de Muffin, en BFF (Backend For Frontend) : c'est le **seul** service qui parle
directement à Postgres, Qdrant, RustFS, Keycloak et au hub LLM. Le frontend et les deux workers
Celery (`worker/document_process`, `worker/agent_execution`) passent tous par ses endpoints HTTP.

## Rôle

- **Auth** : flow OAuth2/OIDC avec Keycloak, session BFF par cookie (`app/core/security`).
- **Collections & documents** : CRUD des collections, upload de fichiers ou scraping d'URL,
  paramètres de chunking/embedding, tags, partage (modèle présent, pas encore branché - voir
  [#13](https://github.com/IA-Generative/Muffin/issues/13)).
- **Runs** : création d'un run de recherche (`POST /api/runs`), suivi de son état/événements,
  reprise après une clarification demandée par l'agent (human-in-the-loop).
- **Endpoints internes** (`/api/internal/*`, préfixe `internal`, protégés par le header
  `X-API-Key` == `WORKER_API_KEY`) : seule porte d'entrée que les deux workers utilisent pour lire/
  écrire en base, dans Qdrant ou dans RustFS. Ni l'un ni l'autre n'a de credentials directs vers
  ces systèmes.
- **Hub LLM** : seul service à détenir la clé API du hub LLM (compatible OpenAI) ; expose
  `/api/models` et `/api/internal/llm/*` pour que les workers génèrent du texte/des embeddings
  sans jamais voir la clé.

## Structure

```
app/
  routers/     endpoints HTTP (publics sous /api, internes sous /api/internal)
  services/    logique métier, appelée par les routers
  repositories/accès base de données (SQLAlchemy async), un par agrégat
  models/      modèles SQLAlchemy
  schemas/     modèles Pydantic (requêtes/réponses)
  config/      classes Settings (pydantic-settings), une par domaine (voir
               docs/environment-variables.md à la racine du repo)
  core/        sécurité (Keycloak, sessions, clé API worker), tâches Celery (producteur),
               stockage RustFS, logging
migrations/    migrations Alembic
tests/         tests pytest (miroir de la structure app/)
```

## Développer

```bash
make back            # serveur de dev avec rechargement à chaud, http://localhost:8000/api/docs
make test-backend    # tests contre un Postgres/Redis jetables
make lint-backend    # ruff check + ruff format --check
make migrate         # applique les migrations Alembic en attente
make migration m="…" # génère une migration à partir des changements de modèles
```

Voir `docs/environment-variables.md` à la racine du repo pour la liste complète des variables
d'environnement lues par ce service.
