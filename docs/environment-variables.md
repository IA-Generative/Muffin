# Variables d'environnement

Référence de toutes les variables d'environnement utilisées dans Muffin : leur définition, leur
valeur par défaut, et les services qui les consomment. Chaque service Python (`backend`,
`worker/document_process`, `worker/agent_execution`) lit ses variables via des classes
`pydantic_settings.BaseSettings` (`case_sensitive=True`, chargées depuis `.env`/`.env.local` puis
l'environnement réel). En local, `docker-compose.yaml` fixe la plupart de ces valeurs directement ;
`${VAR:-default}` dans ce fichier signifie que la variable peut être surchargée depuis un `.env` à
la racine du repo.

Le fichier à utiliser dépend de comment le service tourne :

| Fichier | Lu par | Quand |
|---|---|---|
| `.env` (racine du repo, gitignored) | `docker compose` | Toujours, pour `make up` / `make down` |
| `backend/.env.local` (gitignored) | le backend (pydantic-settings) | Backend lancé hors Docker via `make back` |
| `tests/.env.testing` (tracké) | pytest, via `pytest-dotenv` | `make test-backend` / CI |

`backend/.env.local` prend le pas sur `backend/.env` si les deux existent ; aucun des deux n'est
obligatoire, chaque variable ci-dessous a une valeur par défaut intégrée. Une vraie variable
d'environnement (exportée par Docker Compose ou la CI) l'emporte toujours sur un `.env*`.

## Base de données (Postgres)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `DATABASE_URL` | URL de connexion asyncpg à Postgres (`postgresql+asyncpg://user:pass@host:5432/db`) | `postgresql+asyncpg://muffin:muffin@localhost:5432/muffin` | **backend** (`app/config/database.py` → `app/db.py`, session SQLAlchemy async) |
| `POSTGRES_USER` | Utilisateur créé par l'image officielle `postgres` au premier démarrage | — (fixé à `muffin` dans `docker-compose.yaml`) | Conteneur **postgres** uniquement |
| `POSTGRES_PASSWORD` | Mot de passe de cet utilisateur | — (fixé à `muffin`) | Conteneur **postgres** uniquement |
| `POSTGRES_DB` | Base créée au premier démarrage | — (fixé à `muffin`) | Conteneur **postgres** uniquement |

## Redis (Celery broker/backend + cache)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `REDIS_URL` | URL Redis (broker ET result backend Celery, aussi utilisé comme checkpointer LangGraph côté agent_execution) | `redis://localhost:6379/0` | **backend** (`app/config/redis.py` → `app/core/tasks.py`, producteur Celery), **worker/document_process**, **worker/agent_execution** (`app/config.py`, chacun avec sa propre queue) |

Le broker est un unique `redis-stack-server` partagé ; les deux workers consomment des queues
Celery distinctes (`document_processing`, `agent_execution`) sur ce même Redis, avec une queue
name configurable côté worker (`CELERY_QUEUE_NAME`, non exposée dans `docker-compose.yaml`, garde
sa valeur par défaut en pratique).

## Authentification (Keycloak)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `KEYCLOAK_URL` | URL de Keycloak vue par le backend (nom de service Docker interne, ex. `http://keycloak:8080`) | `http://localhost:8080` | **backend** (`app/config/keycloak.py` → `app/core/security/keycloak_client.py`, `app/routers/auth.py`) |
| `KEYCLOAK_PUBLIC_URL` | URL de Keycloak vue par le navigateur, si différente de `KEYCLOAK_URL` (reverse-proxy) ; retombe sur `KEYCLOAK_URL` si absente | `None` (fallback via la property `public_url`) | idem |
| `KEYCLOAK_REALM` | Nom du realm Keycloak | `muffin` | idem |
| `KEYCLOAK_CLIENT_ID` | Client OAuth2 confidentiel du backend | `muffin-backend` | idem |
| `KEYCLOAK_CLIENT_SECRET` | Secret de ce client | `None` | idem |
| `BACKEND_PUBLIC_URL` | URL publique du backend, utilisée pour construire le `redirect_uri` OAuth2 fixe enregistré côté Keycloak (`{BACKEND_PUBLIC_URL}/api/auth/callback`) | `http://localhost:8000` | idem |
| `FRONTEND_URL` | Origine du frontend : cible de redirection après login/logout, et unique origine autorisée en CORS | `http://localhost:5173` (code) / `http://localhost:8081` (docker-compose, le frontend dockerisé) | **backend** (`app/routers/auth.py`, config CORS) |
| `SESSION_COOKIE_NAME` | Nom du cookie de session | `muffin_session` | **backend** (`app/core/security/factory.py`) |
| `SESSION_COOKIE_SECURE` | Flag `Secure` du cookie de session (doit être `false` en dev HTTP, `true` en prod HTTPS) | `true` | idem |
| `SESSION_COOKIE_SAMESITE` | Politique `SameSite` du cookie (`lax`/`strict`/`none`) | `lax` | idem |
| `SESSION_TTL_SECONDS` | Durée de vie de la session en secondes | `604800` (7 jours) | idem |

Côté conteneur **keycloak** lui-même (pas lu par nos services, mais nécessaire pour le démarrer) :
`KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD` (identifiants admin), `KC_HEALTH_ENABLED`,
`KC_HOSTNAME`, `KC_HOSTNAME_PORT`, `KC_HOSTNAME_STRICT` (config réseau interne à l'image Keycloak).

## LLM hub (OpenAI-compatible)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `OPENAI_API_KEY` | Clé API du hub LLM (compatible API OpenAI, ex. Scaleway) | `""` | **backend** (`app/config/llm.py` → `app/routers/models.py`, `app/routers/internal_llm.py`, `app/services/embedding_model_lookup.py`, `app/services/search_service.py` pour les embeddings) |
| `OPENAI_API_BASE_URL` | URL de base du hub (pas de fallback public OpenAI par défaut : vide → `GET /api/models` répond `503` au lieu de facturer un hub inconnu) | `""` | idem |
| `CHAT_MODELS_CACHE_TTL_SECONDS` | Durée de cache de la liste des modèles de chat disponibles | `3600` | idem |

Ni les workers ni le frontend ne lisent ces variables directement : toute complétion/embedding
passe par le backend (`/internal/llm/*`), qui est seul à détenir la clé.

## Stockage objet (RustFS, compatible S3)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `AWS_ENDPOINT_URL` | Endpoint S3 de RustFS | `http://localhost:9000` | **backend** (`app/config/rustfs.py` → `app/core/storage.py`, URLs présignées), **worker/document_process** (upload des fichiers/screenshots de page) |
| `AWS_ACCESS_KEY_ID` | Clé d'accès S3 | `rustfsadmin` (dev only) | idem |
| `AWS_SECRET_ACCESS_KEY` | Clé secrète S3 | `rustfsadmin` (dev only) | idem |
| `AWS_BUCKET` | Bucket utilisé pour tous les documents/screenshots | `muffin-documents` | idem |

Sans ces variables, `RustFsSettings` retombe sur son défaut `localhost:9000`, qui ne résout à rien
depuis l'intérieur d'un conteneur — les uploads échouent silencieusement avant même la création de
la ligne `Document`.

Le conteneur **rustfs** lui-même consomme en plus (config du service de stockage, pas lues par nos
apps) : `RUSTFS_VOLUMES`, `RUSTFS_ADDRESS`, `RUSTFS_CONSOLE_ADDRESS`, `RUSTFS_CONSOLE_ENABLE`,
`RUSTFS_UNSAFE_BYPASS_DISK_CHECK` (bypass dev-only : les 4 volumes nommés Docker sont sur le même
disque physique, RustFS le refuse par défaut).

## Recherche hybride (Meilisearch)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `MEILI_URL` | URL du serveur Meilisearch | `http://localhost:7700` | **backend** (`app/config/meilisearch.py` → `app/connectors.py`, `app/services/vector_store.py` : upsert/recherche hybride (lexicale + vectorielle) des chunks, QA pairs et résumés embarqués) |
| `MEILI_API_KEY` | Clé API Meilisearch (doit correspondre à `MEILI_MASTER_KEY` côté serveur) | `None` (pas de clé - convient à une instance de dev démarrée sans `MEILI_MASTER_KEY`, jamais en production) | **backend** (`app/config/meilisearch.py`) |

Les workers n'accèdent jamais directement à Meilisearch : toute recherche/écriture vectorielle
passe par les endpoints internes du backend (`/internal/search`, `/internal/qa-search`,
`/internal/summary-search`, `/internal/pipeline/*`).

## Recherche web (SearXNG)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `SEARXNG_URL` | URL de l'instance SearXNG | `http://localhost:8080` | **worker/agent_execution** (`app/config.py` → `app/searxng_client.py`) |

Contrairement à Meilisearch/Postgres, c'est le worker `agent_execution` qui appelle SearXNG
directement (pas via le backend) - aucune donnée utilisateur n'y transite en base, l'appel est
un aller-retour HTTP simple, sans authentification (SearXNG n'en a pas par défaut). L'outil
`web_search` de l'agent n'est appelé que si le run a explicitement activé la recherche web
(toggle du composer de chat, désactivé par défaut - voir `Run.web_search_enabled` côté backend) ;
sans ça, `SEARXNG_URL` n'est jamais sollicité. L'API JSON de SearXNG (`format=json`) est
désactivée par défaut en amont et doit être explicitement activée côté serveur - voir
`docker/searxng/settings.yml` (`search.formats`), monté dans le service `searxng` de
`docker-compose.yaml`.

## Stratégie d'authentification (lue directement depuis `os.environ`, pas via une classe `Settings`)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `VERIFY_TOKEN_MODEL` | Sélectionne le vérificateur de token : `keycloak` (réel, OAuth2/session) ou `full-access` (identité dev fixe, sans Keycloak ni Redis — utilisé par les tests/CI) | `keycloak` | **backend** (`app/core/security/factory.py`) |

## Authentification inter-services (workers ↔ backend)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `WORKER_API_KEY` | Secret partagé, vérifié sur chaque appel `/internal/*` par `app/core/security/worker_auth.py` (dépendance `require_worker_api_key`) | `""` côté backend / `""` côté workers | **backend** (`app/config/worker.py`), **worker/document_process**, **worker/agent_execution**, **worker/evaluation** — doit être identique des deux côtés, sinon tout appel interne échoue en 401 |

## Partage de collections (invitations hashées)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `SHARE_INVITE_PEPPER` | Secret serveur pour le HMAC-SHA256 des identifiants (email/groupe) d'une invitation de partage en attente (`app/core/sharing.py`) - **jamais** un hash nu : un email a trop peu d'entropie pour résister à une attaque par dictionnaire sur une base fuitée sans ce pepper | `""` (partage désactivé tant qu'il n'est pas défini - `POST /api/collections/{id}/shares` répond 503) | **backend** (`app/config/sharing.py`, `app/core/sharing.py`) — un secret fort, généré par environnement, jamais commité ; sa perte ou sa rotation invalide silencieusement toutes les invitations `pending` non encore résolues |

## Backend ↔ workers (URLs)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `BACKEND_API_URL` | URL du backend vue par les workers, base de tous leurs appels `/internal/*` | `http://localhost:8000` | **worker/document_process**, **worker/agent_execution**, **worker/evaluation** (`app/config.py` → clients HTTP `backend_client.py`) |

## Logs

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `LOG_FORMAT` | Format de sortie des logs (`console` lisible en dev, `json` structuré) | `console` | **backend** (`app/config/logging.py` → `app/logger.py`) |
| `LOG_LEVEL` | Niveau de log (`DEBUG`, `INFO`, `WARNING`, ...) | `INFO` | idem |

## worker/document_process — spécifique OCR

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker | `document_processing` | **worker/document_process** (`app/config.py`) |
| `OCR_LANGUAGE` | Code langue Tesseract (ISO 639-2) utilisé pour l'OCR des pages scannées | `fra` | idem (pipeline OCR) |
| `TESSDATA_PATH` | Chemin vers les fichiers de données Tesseract, si non standard — le `Dockerfile` du worker le fixe au chemin du paquet apt `tesseract-ocr-fra` | `None` | idem |

## worker/agent_execution — budgets d'exécution de l'agent

Ces variables bornent le graphe LangGraph de recherche (§28 du brief d'architecture) pour qu'une
requête pathologique ne puisse pas faire tourner indéfiniment le fan-out, le replanning ou la
boucle de vérification (« grounding »).

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker | `agent_execution` | **worker/agent_execution** (`app/config.py`) |
| `MAX_PARALLEL_TASKS` | Nombre max de tâches de recherche exécutées en parallèle (fan-out `Send`) | `4` | idem (`graph/routing/conditions.py`) |
| `MAX_PARALLEL_SEARCHES` | Nombre max de recherches vectorielles en parallèle au sein d'une tâche | `4` | idem |
| `MAX_TOTAL_TASKS` | Plafond cumulé de tâches sur toute la durée d'un run | `12` | idem |
| `MAX_TOTAL_SEARCHES` | Plafond cumulé de recherches sur toute la durée d'un run | `20` | idem |
| `MAX_REPLANS` | Nombre max de replans autorisés | `2` | idem |
| `MAX_GROUNDING_RESEARCHES` | Nombre max de relances de recherche déclenchées par un échec de vérification (grounding) | `1` | idem |
| `SEARCH_RESULTS_PER_QUERY` | Nombre de résultats retournés par recherche vectorielle | `5` | idem |

## worker/evaluation — évaluation du retrieval (issue #11)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker | `evaluation` | **worker/evaluation** (`app/config.py`) |
| `DEFAULT_TOP_K` | Nombre de chunks retrouvés par question quand `k` n'est pas explicitement passé à la tâche | `5` | idem (`app/tasks.py`) |

## Frontend (Vite)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `VITE_API_BASE_URL` | URL de base de l'API backend appelée depuis le navigateur | `http://localhost:8000` (fallback en dur dans chaque composable si la variable est absente) | **frontend** — tous les composables faisant du `fetch` (`useChat.ts`, `useCollections.ts`, `useTasks.ts`, `useCurrentUser.ts`, `useModels.ts`, `useEmbeddingModels.ts`, `useAdminSettings.ts`) et les modals qui chargent des ressources (`SourceDocumentModal.vue`, `DocumentDetailModal.vue`) |

Contrairement aux services Python, cette variable est injectée à la **build** (convention Vite :
préfixe `VITE_`), pas lue au runtime — un changement nécessite de rebuild l'image `frontend`.

## Notes

- Toutes les valeurs `rustfsadmin` / `dev-only-*` fixées dans `docker-compose.yaml` sont explicitement
  marquées « dev only » dans les commentaires du fichier : à ne jamais réutiliser telles quelles en
  production.
- Chaque `Settings` pydantic a `extra="ignore"` : une variable d'environnement inconnue est
  silencieusement ignorée, elle ne fait jamais planter le service au démarrage.
- `case_sensitive=True` partout : `database_url` (minuscule) ne serait pas lu, seul `DATABASE_URL`
  l'est.
