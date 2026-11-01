# Variables d'environnement

Référence de toutes les variables d'environnement utilisées dans Muffin : leur définition, leur
valeur par défaut, et les services qui les consomment. Chaque service Python (`backend`,
`worker/document_process`) lit ses variables via des classes
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
| `REDIS_URL` | URL Redis (broker ET result backend Celery, aussi utilisé comme checkpointer LangGraph par l'agent, qui tourne dans le backend) | `redis://localhost:6379/0` | **backend** (`app/config/redis.py` → `app/core/tasks.py`, producteur Celery), **worker/document_process**, **worker/evaluation**, **worker/document_edit** (`app/config.py`, chacun avec sa propre queue) |

Le broker est un unique `redis-stack-server` partagé ; chaque worker consomme ses propres queues
Celery sur ce même Redis (`document_extraction`, `document_enrichment`, `document_import`,
`index_rebuild` pour worker/document_process, voir son README ; `evaluation`,
`document_edit` pour les autres). Les noms sont configurables côté worker mais gardent leur valeur
par défaut en pratique, et doivent correspondre à ceux de `backend/app/core/tasks.py`.

## Authentification (Keycloak)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `KEYCLOAK_URL` | URL de Keycloak vue par le backend (nom de service Docker interne, ex. `http://keycloak:8080`) | `http://localhost:8080` | **backend** (`app/config/keycloak.py` → `app/core/security/keycloak_client.py`, `app/routers/auth.py`) |
| `KEYCLOAK_PUBLIC_URL` | URL de Keycloak vue par le navigateur, si différente de `KEYCLOAK_URL` (reverse-proxy) ; retombe sur `KEYCLOAK_URL` si absente | `None` (fallback via la property `public_url`) | idem |
| `KEYCLOAK_REALM` | Nom du realm Keycloak | `muffin` | idem |
| `KEYCLOAK_CLIENT_ID` | Client OAuth2 confidentiel du backend | `muffin-backend` | idem |
| `KEYCLOAK_CLIENT_SECRET` | Secret de ce client | `None` | idem |
| `BACKEND_PUBLIC_URL` | URL publique du backend, utilisée pour construire le `redirect_uri` OAuth2 fixe enregistré côté Keycloak (`{BACKEND_PUBLIC_URL}/api/auth/callback`) | `http://localhost:8000` (code) / `http://localhost:8000` (docker-compose, surchargeable via `.env`) | idem |
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

## Recherche hybride (Qdrant)

Moteur, modèle de données, BM25 et RRF : voir [docs/search.md](search.md). Sauvegarde : [docs/qdrant-backup.md](qdrant-backup.md).

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `QDRANT_URL` | URL du serveur Qdrant | `http://localhost:6333` | **backend** (`app/config/qdrant.py` → `app/connectors.py`, `app/services/vector_store.py` : upsert/recherche hybride (dense + BM25) des chunks, QA pairs et résumés embarqués) |
| `QDRANT_API_KEY` | Clé API Qdrant (doit correspondre à `QDRANT__SERVICE__API_KEY` côté serveur) | `None` (pas de clé - convient à une instance de dev démarrée sans clé, jamais en production) | **backend** (`app/config/qdrant.py`) |
| `SEARCH_RRF_K` | Constante `k` de la fusion RRF : une position `r` d'une branche ajoute `poids / (k + r)` au score fusionné. Plus `k` est petit, plus la fusion favorise ce que chaque branche classe en tête | `60` | **backend** (`app/config/qdrant.py` → `vector_store._hybrid`) |
| `SEARCH_DENSE_WEIGHT` / `SEARCH_SPARSE_WEIGHT` | Poids de la branche dense (embedding) et de la branche lexicale (BM25) dans la fusion | `1.0` / `1.0` | **backend** (idem) |
| `SEARCH_PREFETCH_LIMIT` | Candidats que chaque branche remet à la fusion, avant la limite finale | `50` | **backend** (idem) |
| `SEARCH_BM25_K1` / `SEARCH_BM25_B` | Saturation de la fréquence d'un terme (`k1`) et normalisation par la longueur du texte (`b`) de BM25 | `1.2` / `0.75` | **backend** (`app/core/bm25.py`) |
| `SEARCH_BM25_AVG_LENGTH` | Longueur moyenne, en termes, d'un texte indexé (un chunk) - Qdrant ne la fournit pas | `200` | **backend** (idem) |
| `SEARCH_LANGUAGE` | Langue de la racinisation et des mots vides (algorithme Snowball : `french`, `english`...), identique à l'indexation et à la requête. **Changer la langue impose de ré-indexer** | `french` | **backend** (idem) |
| `SEARCH_LOG_BRANCHES` | Journalise (niveau debug), pour chaque recherche, le rang que chaque branche donnerait seule à chaque résultat (requêtes supplémentaires : pour le débogage) | `false` | **backend** (`vector_store._log_branches`) |
| `SEARCH_EMBEDDING_CACHE_SECONDS` | Durée (secondes) pendant laquelle l'embedding d'une question est gardé, par modèle (Redis), et partagé entre les recherches faites en même temps : une même question coûte un seul appel au modèle d'embedding. `0` : désactivé | `900` | **backend** (`app/config/qdrant.py` → `search_service.embed_query`) |
| `OWUI_QDRANT_PREFIX` | Préfixe des collections Qdrant d'Open WebUI (son `QDRANT_COLLECTION_PREFIX`, mode classique) : une collection copiée d'Open WebUI est lue dans `<préfixe>_<id de la knowledge base>` (#453) | `open-webui` | **backend** (`vector_store.external_collection_name`) |

Les workers n'accèdent jamais directement à Qdrant : toute recherche/écriture vectorielle
passe par les endpoints internes du backend (`/internal/search`, `/internal/qa-search`,
`/internal/summary-search`, `/internal/pipeline/*`).

Le conteneur **qdrant** lui-même lit `QDRANT__SERVICE__API_KEY` (docker-compose : la valeur de `QDRANT_API_KEY`, par défaut
`dev-only-qdrant-key-not-for-prod` ; Helm : le secret Vault `muffin-qdrant`).

## Outils de recherche MCP (#467)

Lues par le backend. Les valeurs par défaut valent quand un appel ne précise rien ; les plafonds, jamais dépassés.

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `MCP_SEARCH_MODEL` | Modèle de chat qui découpe la question en sous-questions. Vide : le premier modèle de chat du hub | — | **backend** (`McpSearchService`) |
| `MCP_SEARCH_MAX_SUB_QUERIES` / `MCP_SEARCH_MAX_SUB_QUERIES_CEILING` | Sous-questions au plus, par défaut et plafond | `4` / `8` | **backend** |
| `MCP_SEARCH_MAX_COLLECTIONS` / `MCP_SEARCH_MAX_COLLECTIONS_CEILING` | Collections interrogées par sous-question, par défaut et plafond | `3` / `10` | **backend** |
| `MCP_SEARCH_LIMIT` / `MCP_SEARCH_LIMIT_CEILING` | Sources renvoyées par sous-question, par défaut et plafond | `5` / `20` | **backend** |
| `MCP_SUGGEST_LIMIT` / `MCP_SUGGEST_LIMIT_CEILING` | Collections proposées par `suggest_collections`, par défaut et plafond | `5` / `20` | **backend** |

## Recherche web (SearXNG)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `SEARXNG_URL` | URL de l'instance SearXNG | `http://localhost:8080` | **backend** (`app/agent/config.py` → `app/agent/searxng_client.py`) |

Contrairement à Qdrant/Postgres, c'est l'agent (qui tourne dans le backend) qui appelle SearXNG
directement - aucune donnée utilisateur n'y transite en base, l'appel est
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
| `WORKER_API_KEY` | Secret partagé, vérifié sur chaque appel `/internal/*` par `app/core/security/worker_auth.py` (dépendance `require_worker_api_key`) | `""` côté backend / `""` côté workers | **backend** (`app/config/worker.py`, aussi pour les appels de l'agent à ses propres routes), **worker/document_process**, **worker/evaluation**, **worker/document_edit** — doit être identique des deux côtés, sinon tout appel interne échoue en 401 |

## Partage de collections (invitations hashées)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `SHARE_INVITE_PEPPER` | Secret serveur pour le HMAC-SHA256 des identifiants (email/groupe) d'une invitation de partage en attente (`app/core/sharing.py`) - **jamais** un hash nu : un email a trop peu d'entropie pour résister à une attaque par dictionnaire sur une base fuitée sans ce pepper | `""` (partage désactivé tant qu'il n'est pas défini - `POST /api/collections/{id}/shares` répond 503) | **backend** (`app/config/sharing.py`, `app/core/sharing.py`) — un secret fort, généré par environnement, jamais commité ; sa perte ou sa rotation invalide silencieusement toutes les invitations `pending` non encore résolues |

## Documents vivants

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `DOCUMENT_LOCK_TTL_SECONDS` | Durée de validité, en secondes, du verrou d'édition souple d'un document vivant (`POST /api/collections/{id}/documents/{doc}/lock`) tant qu'il n'est pas renouvelé (`PUT`). Passé ce délai le verrou est ignoré, un onglet abandonné libère donc le document tout seul | `600` | **backend** (`app/config/documents.py`, `app/services/living_document_service.py`) |
| `DOCUMENT_MAX_UPLOAD_BYTES` | Taille maximale d'un fichier déposé (collection, conversation, fichiers à ranger), en octets ; au-delà, refusé en 413. Non défini : pas de limite. Le fichier est envoyé en streaming vers le stockage, jamais chargé entier en mémoire | aucune | **backend** (`app/config/documents.py`, `app/services/document_upload_service.py`) |
| `IMPORT_PROCESSING_WINDOW` | Nombre de documents d'un même import ZIP en cours d'extraction à la fois (#335) : les autres attendent, hors de la file, et la fin d'une extraction libère le suivant. Une archive de 2000 fichiers ne remplit donc plus la file | `4` | **backend** (`app/config/documents.py`, `app/services/document_upload_service.py`) |
| `IMPORT_SLOT_TIMEOUT_SECONDS` | Au bout de ce délai, un document libéré mais jamais extrait (tâche perdue) ne retient plus sa place dans la fenêtre de son import | `14400` | **backend** (`app/config/documents.py`, `app/services/document_upload_service.py`) |
| `PINNED_DESCENDANTS_LIMIT` | Nombre max de sous-collections ajoutées quand l'utilisateur épingle une collection dans le chat (les plus proches d'abord) ; au-delà, l'agent propose d'aller plus loin depuis la collection épinglée la plus proche | `30` | **backend** (`app/config/runs.py`, `app/services/run_service.py`) |
| `API_KEY_PEPPERS` | Secrets avec lesquels les clés d'API personnelles sont hachées (#521, `docs/api-keys.md`), `version=secret` séparés par des virgules : le **premier** hache les nouvelles clés, les autres servent seulement à vérifier (`v2=…,v1=…` pour une rotation sans couper une clé). Vide : les clés d'API sont désactivées (`POST /api/api-keys` répond 503). Un secret fort par environnement, **jamais commité** ; sa perte invalide toutes les clés | `""` (désactivé ; `docker-compose.yaml` en fournit un d'essai) | **backend** (`app/config/api_keys.py`, `app/core/api_keys.py`) |
| `OPENAI_API_RETENTION_DAYS` | Durée de conservation, en jours, des conversations créées par l'API compatible OpenAI (#513, `docs/openai-api.md`) ; elles sont purgées ensuite | `7` | **backend** (`app/config/openai_api.py`) |
| `OPENAI_API_RUNS_PER_USER` | Nombre de réponses qu'un utilisateur peut avoir en cours par l'API compatible OpenAI, par pod (au-delà : 429) | `3` | **backend** (`app/config/openai_api.py`) |
| `OPENAI_API_MAX_MESSAGES` / `OPENAI_API_MAX_MESSAGE_CHARS` | Taille maximale de l'historique d'une requête (messages) et d'un message (caractères) | `40` / `20000` | **backend** (`app/config/openai_api.py`) |
| `OPENAI_API_TIMEOUT_SECONDS` | Délai après lequel une requête sans réponse est annulée (504) ; l'ingress coupe à 600 s | `540` | **backend** (`app/config/openai_api.py`) |
| `OPENAI_API_MAX_LISTED_COLLECTIONS` | Nombre de collections de premier niveau listées comme modèles par `GET /v1/models`, en plus de `muffin` | `100` | **backend** (`app/config/openai_api.py`) |
| `RERANK_API_URL` | URL complète du service de reclassement (route `/rerank` de Cohere, Jina ou vLLM, #511, `docs/search.md`). **Vide : reclassement éteint**, aucun appel | `""` | **backend** (`app/config/rerank.py` → `app/services/reranker.py`) |
| `RERANK_API_KEY` / `RERANK_MODEL` | Clé (envoyée en `Authorization: Bearer`) et nom du modèle du service de reclassement | `""` / `""` | **backend** (`app/config/rerank.py`) |
| `RERANK_CANDIDATES` | Passages lus avant reclassement quand une collection de la recherche l'a activé ; les `limit` meilleurs sont gardés | `40` | **backend** (`app/config/rerank.py`) |
| `RERANK_TIMEOUT_SECONDS` / `RERANK_PASSAGE_MAX_CHARS` | Délai maximal d'attente du service (au-delà : l'ordre actuel est gardé) et longueur à laquelle un passage est coupé avant l'envoi | `3` / `2000` | **backend** (`app/config/rerank.py`) |
| `ASSISTANTS_PUBLIC_ENABLED` | Autorise tout utilisateur à rendre un assistant public dans l'organisation (#514, `docs/assistants.md`). Faux : seul un administrateur le peut, et il peut toujours retirer un assistant public | `false` | **backend** (`app/config/assistants.py`) |
| `ASSISTANTS_PER_USER` | Nombre d'assistants qu'une personne peut créer | `100` | **backend** (`app/config/assistants.py`) |
| `ASSISTANTS_SEARCH_INDEX_MIN` | Sous ce nombre d'assistants à parcourir, la recherche se fait sur leurs mots, sans appel au modèle d'embedding ni à l'index (#531, `docs/assistants.md`) | `8` | **backend** (`app/config/assistants.py`) — le frontend a la même valeur dans `utils/assistantSearch.ts` |
| `ASSISTANTS_SEARCH_LIMIT` | Nombre maximal d'assistants qu'une recherche renvoie | `20` | **backend** (`app/config/assistants.py`) |
| `ASSISTANTS_SUGGEST_MIN_SCORE` | Cosinus minimal entre une question et la description d'un assistant pour le proposer | `0.45` | **backend** (`app/config/assistants.py`) |
| `ASSISTANTS_CONSULT_MAX` | Nombre maximal d'autres assistants qu'un assistant consulte pour une question ; au-delà, les plus proches de la question sont gardés | `5` | **backend** (`app/config/assistants.py`) |
| `TOOLS_ALLOWED_DOMAINS` | Domaines (et sous-domaines) autorisés pour l'adresse d'un serveur d'outils MCP, séparés par des virgules (#343, `docs/tools.md`). Vide : toute adresse publique | `""` | **backend** (`app/config/tools.py` → `app/core/url_guard.py`) |
| `TOOLS_ALLOW_PRIVATE_ADDRESSES` | **Poste de développement seulement** : laisse un serveur d'outils être sur une adresse privée ou locale. Jamais en production : c'est un accès au réseau interne (SSRF) | `false` | **backend** (`app/config/tools.py`) |
| `TOOLS_CALL_TIMEOUT_SECONDS` / `TOOLS_OUTPUT_MAX_CHARS` | Délai maximal d'un appel d'outil, et nombre de caractères gardés de sa réponse (le reste est coupé) | `20` / `6000` | **backend** (`app/config/tools.py`) |
| `TOOLS_CALLS_PER_RUN` / `TOOLS_CALLS_PER_USER_PER_MINUTE` | Quotas d'appels d'outils par run et par personne et par minute (compteurs Redis) ; au-delà, l'appel répond `quota_depasse`, rien n'échoue | `5` / `30` | **backend** (`app/config/tools.py`) |
| `TOOL_SERVERS_PER_USER` / `TOOLS_OFFERED_MAX` / `TOOLS_PER_SERVER_MAX` | Nombre de serveurs qu'une personne ajoute, nombre d'outils décrits au modèle à la fois, et d'outils qu'un serveur peut apporter | `10` / `12` / `100` | **backend** (`app/config/tools.py`) |
| `TOOLS_SELECTED_MAX` / `TOOLS_SEARCH_LIMIT` / `TOOLS_SEARCH_INDEX_MIN` | Recherche des outils par leur description (#530, `docs/search.md`) : combien d'outils de serveurs le modèle reçoit au plus quand il y en a davantage (ceux de Muffin sont toujours là), plafond d'une recherche, et nombre d'outils sous lequel on compare les mots sur place, sans embedding ni Qdrant | `8` / `20` / `8` | **backend** (`app/config/tools.py`) |
| `TOOLS_PENDING_HOURS` / `TOOLS_PENDING_PER_USER` | Durée pendant laquelle une demande d'accord pour un outil qui modifie des données attend la décision (heures), et nombre de demandes en attente par personne ; au-delà, la demande expire / est refusée avec `quota_depasse` | `24` / `20` | **backend** (`app/config/tools.py`) |
| `IMAGES_PER_USER_PER_MINUTE` / `IMAGES_PER_RUN` / `IMAGES_PROMPT_MAX_CHARS` | Génération d'images (#518, `docs/image-generation.md`) : demandes qu'une personne peut lancer par minute (tous les essais comptent), images qu'une réponse de l'assistant peut demander (outil `generer_image`), et longueur maximale de la description envoyée au fournisseur. L'activation, l'adresse, la clé, le modèle, le quota du jour, le poids maximal et les groupes autorisés sont des réglages d'administration (*Administration → Génération d'images*), pas des variables | `5` / `2` / `4000` | **backend** (`app/config/images.py`) |
| `IMAGES_PER_MESSAGE` / `IMAGES_ATTACH_MAX_BYTES` / `IMAGES_STAGED_MAX` / `IMAGES_STAGED_TTL_HOURS` | Images jointes à un message pour qu'un modèle de vision les lise (#512, `docs/image-attachments.md`) : nombre par message, poids maximal de chacune (octets ; la page réduit les grandes avant l'envoi), nombre d'images choisies et pas encore envoyées par personne, et durée de conservation de celles qui ne sont jamais envoyées (heures) | `4` / `5242880` / `12` / `24` | **backend** (`app/config/images.py`) |
| `IMAGES_REQUEST_TIMEOUT_SECONDS` / `IMAGES_DOWNLOAD_TIMEOUT_SECONDS` | Temps laissé au fournisseur pour faire une image, et pour récupérer une image qu'il donne par adresse (secondes) | `120` / `20` | **backend** (`app/config/images.py`) |
| `IMAGES_MAX_BYTES_LIMIT` / `IMAGES_MAX_SIDE` | Ce qu'aucun réglage ne dépasse : poids d'une image (octets) et plus grand côté (pixels) | `26214400` / `8192` | **backend** (`app/config/images.py`) |
| `SECRETS_PROVIDER` | Où sont chiffrés les secrets que Muffin doit relire (#521, `docs/secrets.md`) : `vault` (Transit : la clé reste dans Vault) ou `local` (AES-256-GCM, jeu de clés de la configuration : développement, tests, déploiement sans Vault) | `local` | **backend** (`app/config/secrets.py`, `app/core/secret_store`) |
| `SECRETS_REQUIRE_VAULT` | `true` pour que l'application **refuse de démarrer** si le fournisseur n'est pas Vault : pour une production, où `local` ne serait qu'une erreur | `false` | **backend** (`app/core/secret_store/__init__.py`, `app/main.py`) |
| `SECRETS_LOCAL_KEYS` | Jeu de clés du fournisseur local : `id=base64 de 32 octets` séparés par des virgules, la **première** chiffre, les autres ne font que déchiffrer (changer de clé sans perdre un secret). Un secret fort par environnement, **jamais commité** ; `docker-compose.yaml` en fournit un d'essai | `""` (aucun secret ne peut être stocké) | **backend** (`app/config/secrets.py`, `app/core/secret_store/local.py`) |
| `VAULT_ADDR` | Adresse de Vault (`https://vault.example:8200`) | `""` | **backend** (`app/config/secrets.py`, `app/core/secret_store/vault.py`) |
| `VAULT_TRANSIT_MOUNT` / `VAULT_TRANSIT_KEY` | Montage du moteur Transit et nom de la clé (créée avec `derived=true`) | `transit` / `muffin-secrets` | **backend** (`app/config/secrets.py`) |
| `VAULT_AUTH_METHOD` | `kubernetes` (le compte de service du pod contre un jeton court de Vault, renouvelé) ou `token` (un jeton donné : développement) | `kubernetes` | **backend** (`app/config/secrets.py`, `app/core/secret_store/vault.py`) |
| `VAULT_TOKEN` | Jeton de Vault, pour `VAULT_AUTH_METHOD=token` seulement | `""` | **backend** (`app/config/secrets.py`) |
| `VAULT_K8S_ROLE` / `VAULT_K8S_AUTH_MOUNT` / `VAULT_K8S_JWT_PATH` | Rôle Vault du pod, montage de la méthode d'authentification Kubernetes, fichier du jeton du compte de service | `muffin` / `kubernetes` / `/var/run/secrets/kubernetes.io/serviceaccount/token` | **backend** (`app/config/secrets.py`) |
| `VAULT_NAMESPACE` | Espace de noms de Vault (Enterprise) | `""` | **backend** (`app/config/secrets.py`) |
| `VAULT_CA_CERT` | Chemin du certificat de l'autorité de Vault, quand le système ne la connaît pas | `""` | **backend** (`app/config/secrets.py`) |
| `VAULT_TIMEOUT_SECONDS` | Délai d'un appel à Vault ; passé ce délai, la fonction qui avait besoin du secret répond 503 | `5.0` | **backend** (`app/config/secrets.py`) |
| `API_KEYS_PER_USER` | Nombre de clés d'API valides (ni révoquées ni expirées) qu'un utilisateur peut avoir en même temps | `10` | **backend** (`app/config/api_keys.py`, `app/services/api_key_service.py`) |
| `API_KEY_DEFAULT_DAYS` | Durée de validité d'une clé d'API quand la demande n'en précise pas | `90` | **backend** (`app/config/api_keys.py`) |
| `API_KEY_MAX_DAYS` | Durée de validité maximale d'une clé d'API : une clé expire toujours | `365` | **backend** (`app/config/api_keys.py`) |
| `API_KEY_RATE_LIMIT_PER_MINUTE` | Nombre de requêtes par minute qu'une clé d'API peut faire ; au-delà, `429` avec `Retry-After` | `120` | **backend** (`app/config/api_keys.py`, `app/services/api_key_service.py`) |
| `RUN_STREAM_TTL_SECONDS` | Durée, en secondes, pendant laquelle le flux en direct d'un run (`GET /api/runs/{id}/stream`, #510) reste lisible après sa dernière écriture : un chat rechargé en plein run y retrouve ses étapes et le début de la réponse ; passé ce délai, il lit le run lui-même | `900` | **backend** (`app/config/runs.py`, `app/services/run_stream.py`) |
| `RUN_STREAM_MAXLEN` | Nombre maximal d'entrées gardées par flux de run (étapes, morceaux de réponse, statuts) ; les plus anciennes sont écartées au-delà | `20000` | **backend** (`app/config/runs.py`, `app/services/run_stream.py`) |
| `RUN_STREAMS_PER_USER` | Nombre de flux en direct qu'un utilisateur peut tenir ouverts en même temps, **par pod** ; au-delà, `429` et le chat suit le run par interrogation | `8` | **backend** (`app/config/runs.py`, `app/routers/runs.py`) |
| `RUN_STREAM_PING_SECONDS` | Intervalle, en secondes, des messages `ping` d'un flux au repos : ils empêchent un proxy de couper un flux silencieux, et le serveur en profite pour vérifier l'état réel du run en base | `15` | **backend** (`app/config/runs.py`, `app/routers/runs.py`) |

## Backend ↔ workers (URLs)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `BACKEND_API_URL` | URL du backend vue par les workers, base de tous leurs appels `/internal/*` | `http://localhost:8000` | **worker/document_process**, **worker/evaluation**, **worker/document_edit** (`app/config.py` → clients HTTP `backend_client.py`) |

## Logs

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `LOG_FORMAT` | Format de sortie des logs (`console` lisible en dev, `json` structuré). Dans les workers, chaque ligne émise pendant une tâche porte `celery_task_id`, `task_name`, `document_id`, `collection_id` | `console` | **backend** (`app/config/logging.py` → `app/logger.py`), **tous les workers** (`app/config.py` → `app/task_logging.py`) |
| `LOG_LEVEL` | Niveau de log sur stdout (`DEBUG`, `INFO`, `WARNING`, ...) | `INFO` | idem |
| `TASK_LOG_LEVEL` | Niveau à partir duquel les lignes d'une tâche sont envoyées au backend (#305), pour être suivies en direct dans Muffin | `INFO` | **tous les workers** |
| `TASK_LOG_RETENTION_DAYS` | Durée de conservation des lignes de log des tâches (purgées chaque heure par le beat de `document_process`) | `7` | **backend** |
| `ENERGY_WATTS_PER_CORE` | Puissance d'un cœur de CPU qui travaille, pour estimer l'énergie (Wh) affichée dans « Ma consommation » à partir du temps CPU des tâches des workers | `10` | **backend** (`app/config/energy.py`) |
| `ENERGY_WATTS_PER_GB` | Puissance de la mémoire occupée par une tâche, par Go et pendant sa durée | `0.375` | **backend** |
| `ENERGY_PUE` | PUE du centre de données (refroidissement et distribution électrique ajoutés à la consommation des machines) | `1.2` | **backend** |

## worker/document_process — spécifique OCR

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `EXTRACTION_QUEUE_NAME` | Queue Celery de l'extraction (OCR, parsing, fetch d'URL), pod `document_process` (#291) - doit correspondre à `DOCUMENT_EXTRACTION_QUEUE` de `backend/app/core/tasks.py` | `document_extraction` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `ENRICHMENT_QUEUE_NAME` | Queue Celery de l'enrichissement (embeddings, appels LLM), pod `document_enrichment` (#291) - doit correspondre à `DOCUMENT_ENRICHMENT_QUEUE` du backend | `document_enrichment` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `IMPORT_QUEUE_NAME` | Queue Celery des imports ZIP (#223), pod `index_rebuild` (#291) - doit correspondre à `DOCUMENT_IMPORT_QUEUE` du backend | `document_import` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `REBUILD_QUEUE_NAME` | Queue Celery des reconstructions blue/green d'index (#12), pod `index_rebuild` - doit correspondre à `INDEX_REBUILD_QUEUE` de `backend/app/core/tasks.py` | `index_rebuild` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `LEGACY_QUEUE_NAME` | La queue unique d'avant #291, encore vidée par le pod d'extraction pendant une release pour ne rien perdre à la bascule - à retirer ensuite | `document_processing` | **worker/document_process** (`app/config.py`, `Dockerfile`) |
| `OCR_LANGUAGE` | Code langue Tesseract (ISO 639-2) utilisé pour l'OCR des pages scannées | `fra` | idem (pipeline OCR) |
| `OCR_ENGINE` | Ce qui lit les pages scannées : `tesseract` (l'OCR de liteparse) ou `layout` (les pods d'OCR par layout, voir `worker/document_process/README.md`, avec Tesseract en repli pour une page qu'ils ne lisent pas). **Défaut du code : `tesseract`** - un déploiement qui ne configure rien ne change pas ; le chart (`helm/values/common-values.yaml`) et le `docker-compose.yaml` le mettent à `layout`. **À régler à l'identique dans les trois pods de `worker/document_process`** (extraction, enrichissement, reconstruction d'index) : le découpage et le résumé tournent dans le pod d'enrichissement et calculent leur empreinte (#300) à partir de celle de l'extraction, qui dépend de ce réglage - un pod en désaccord casse la réutilisation des résultats d'un même fichier, sans erreur | `tesseract` | **worker/document_process** (`app/config.py`, `app/ocr/scanned.py`, `app/reuse.py`) |
| `LAYOUT_QUEUE_NAME` / `OCR_QUEUE_NAME` / `TABLE_QUEUE_NAME` | Queues Celery des pods d'OCR par layout (détection des régions, lecture du texte, structure des tableaux). Propres au worker : le backend n'y envoie jamais. Le pod d'extraction envoie à ces queues, il ne les consomme pas | `document_layout` / `document_ocr` / `document_table` | **worker/document_process** (`app/config.py`, `app/celery_app.py`, `app/ocr/routing.py`) |
| `VISION_QUEUE_NAME` | Queue réservée au futur pod `vision` (descriptions des images et des tableaux) | `document_vision` | idem |
| `OCR_SCANNED_MIN_CHARS` | Une page est lue par les pods d'OCR (`OCR_ENGINE=layout`) quand liteparse dit qu'elle est scannée ou que son texte est illisible, ou qu'elle a moins de ce nombre de caractères natifs **et** des images (une page blanche n'est pas envoyée) | `20` | **worker/document_process** (`app/config.py`, `app/ocr/scanned.py`) |
| `OCR_PAGE_WINDOW` | Nombre de pages d'un même document entre les mains des pods à la fois (le layout puis le texte d'une page) : la file d'un pod n'en reçoit jamais plus, comme `PARSE_WINDOW` pour les plages | `4` | idem |
| `OCR_STAGE_TIMEOUT_SECONDS` | Durée maximale d'une étape d'une page (le layout, puis le texte), à partir de son envoi - l'attente dans la file derrière les pages d'autres documents comprise. Au-delà, la tâche envoyée est révoquée et la page retombe sur l'OCR de liteparse (Tesseract) | `900` | idem |
| `OCR_POLL_SECONDS` | Intervalle auquel la tâche d'extraction regarde les résultats des pods (et si elle a été révoquée, #326) | `0.5` | idem |
| `OCR_PIPELINE_VERSION` | Fait partie de l'empreinte de l'extraction (#300) : à augmenter quand les modèles des pods changent (ils sont dans les pods, pas dans ce worker), sinon un fichier extrait avec les anciens serait pris pour extrait avec les nouveaux. N'entre dans l'empreinte que pour `OCR_ENGINE=layout` | `1` | idem (`app/reuse.py`) |
| `OCR_READ_TABLES_AS_TEXT` | `true` : les cellules d'un tableau d'une page scannée sont lues comme du texte, une ligne du tableau par ligne du markdown (aucun pod `table` nécessaire). `false` : le pod `table` les lit comme des tableaux (#410) - le markdown de la page ne garde qu'un **marqueur** `[Tableau <document>/p3/t1 — colonnes : A \| B — N lignes]`, et le contenu est gardé en base, que l'agent va lire. **Défaut du code : `true`** ; le chart et le compose le mettent à `false`. Comme `OCR_ENGINE`, **le même dans les trois pods** de `worker/document_process` (il entre dans l'empreinte, #300) | `true` | idem |
| `OCR_TABLE_MIN_SCORE` | Score minimal d'un tableau lu par le pod `table` pour être tenu pour fiable. En dessous il est gardé quand même, avec `reliable=false` et « structure douteuse » dans son marqueur (un tableau sans bordures lu faux a eu 0,49, les deux bien lus 1,0 et 0,999). Entre dans l'empreinte (#300) | `0.6` | idem |
| `OCR_PAGE_DPI` | Résolution à laquelle une page est rendue avant d'être confiée aux pods d'OCR | `200` | idem |
| `OCR_REGION_MIN_SCORE` | Score minimal d'une région détectée ; en dessous, elle est écartée | `0.5` | idem |
| `OCR_REGION_MIN_PIXELS` | Taille minimale d'une région, en pixels sur son plus petit côté ; en dessous, c'est de la poussière | `32` | idem |
| `OCR_MAX_REGIONS_PER_PAGE` | Nombre maximal de régions gardées par page (les scores les plus bas partent d'abord) | `200` | idem |
| `MODELS_DIR` | Dossier des modèles dans l'image d'un pod d'OCR : en lecture seule, rien n'est téléchargé à l'exécution | `/models` | idem |
| `LAYOUT_TASK_SOFT_TIME_LIMIT_SECONDS` / `OCR_TASK_SOFT_TIME_LIMIT_SECONDS` / `TABLE_TASK_SOFT_TIME_LIMIT_SECONDS` | Limite souple de la tâche d'une page dans chaque pod : une exception levée dans la tâche, jamais un kill (#294) | `300` | idem |
| `OCR_PARSE_TIMEOUT_SECONDS` | Délai maximal d'un parsing de document - ou d'une plage de pages d'un long PDF (`PARSE_RANGE_PAGES`) - (#294) : au-delà, le processus du parseur est tué et remplacé, et le document passe en erreur. Remplace l'ancienne limite de 5 minutes sur toute la tâche | `3600` | **worker/document_process** (`app/config.py`, `app/parsing.py`) |
| `TASK_SOFT_TIME_LIMIT_SECONDS` | Limite souple de toute tâche : une exception levée dans la tâche, jamais un kill (#294). Seuls les pods en prefork l'appliquent (pas le pool de threads) | `7200` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `IMPORT_SOFT_TIME_LIMIT_SECONDS` | Au-delà, un import ZIP se termine en `failed` avec le résumé de ce qui a été créé, au lieu de rester « en cours » | `7200` | **worker/document_process** (`app/config.py`, `app/tasks/import_zip.py`) |
| `REBUILD_SLICE_SECONDS` / `REBUILD_MAX_SLICES` | Une reconstruction d'index (reprenable) tourne par tranches : à la fin d'une, une nouvelle tâche reprend où la base en est. Au-delà du nombre de tranches (24 h), elle échoue | `10800` / `8` | **worker/document_process** (`app/config.py`, `app/tasks/rebuild.py`) |
| `BROKER_VISIBILITY_TIMEOUT_SECONDS` | Délai avant que Redis redonne une tâche non acquittée à un autre worker. Doit dépasser toutes les limites ci-dessus, sinon une tâche longue tournerait deux fois ; c'est aussi le délai de reprise d'une tâche dont le worker est mort (1 h par défaut chez Redis) | `14400` | **worker/document_process** (`app/config.py`, `app/celery_app.py`) |
| `URL_FETCH_CONNECT_TIMEOUT_SECONDS` | Délai pour se connecter au site d'une URL : un site injoignable échoue vite | `30` | **worker/document_process** (`app/config.py`, `app/scraping.py`) |
| `URL_FETCH_TIMEOUT_SECONDS` | Délai pour télécharger une URL une fois connecté, fichier servi compris (un gros PDF sur un site lent) | `1800` (30 min) | idem |
| `CHUNKING_LLM_CONCURRENCY` | Nombre de fenêtres de pages pour lesquelles le découpage par LLM interroge le modèle en même temps | `8` | **worker/document_process** (`app/config.py`, `app/chunking.py`) |
| `EMBED_BATCH_SIZE` | Nombre de chunks embeddés en un seul appel au hub | `64` | idem (`app/tasks/chunk.py`) |
| `PAGE_WRITE_CONCURRENCY` | Nombre de pages d'un fichier écrites en même temps (capture d'écran stockée, texte envoyé au backend) | `8` | idem (`app/tasks/process.py`) |
| `PARSE_RANGE_PAGES` | Un PDF de plus de pages que cela est extrait par plages de ce nombre de pages, chacune par une tâche à elle (`parse_page_range`, #331) ; le délai `OCR_PARSE_TIMEOUT_SECONDS` s'applique à chaque plage. Fait partie de l'empreinte de l'extraction (#300) | `25` | idem (`app/config.py`, `app/tasks/process.py`) |
| `PARSE_WINDOW` | Nombre de plages d'un même document extraites en même temps : une plage qui se termine lance la suivante, la file n'en contient jamais plus | `4` | idem |
| `SYNC_SUMMARY_WORDS_PER_PAGE` | Un fichier copié d'un autre système (Open WebUI, #457) a son texte sur une seule page : il est découpé, en mémoire seulement, en pages fictives de ce nombre de mots pour que le résumé travaille par pages (`summary_pages_per_map`). Rien n'est écrit ni cité | `500` | idem |
| `ENRICHMENT_WINDOW` | Nombre de fenêtres de pages d'un même document, par étape (QA, entités), envoyées en même temps : une fenêtre qui se termine envoie la suivante de sa voie, la file n'en contient jamais plus. Les documents passent à tour de rôle au lieu que les mille fenêtres de l'un fassent attendre le suivant | `4` | idem |
| `STORAGE_CONNECT_TIMEOUT_SECONDS` / `STORAGE_READ_TIMEOUT_SECONDS` | Délais de connexion à RustFS/S3 et d'attente des octets suivants d'un transfert (3 nouvelles tentatives) | `10` / `60` | **worker/document_process** (`app/config.py`, `app/storage.py`) |
| `IMPORT_BATCH_FILES` | Nombre de fichiers d'un ZIP lus par une même tâche `import_zip_batch` (#334) : l'archive est découpée en lots de cette taille. Une archive qui tient en un lot est lue par `import_zip` lui-même | `50` | **worker-document-process** (`app/config.py`, `app/tasks/import_zip.py`) |
| `IMPORT_WINDOW` | Nombre de lots d'un même import lus en même temps : un lot qui se termine lance le suivant, la file n'en contient jamais plus | `4` | idem |
| `ZIP_IMPORT_MAX_FILES` | Nombre maximal de fichiers d'un ZIP importé ; au-delà, l'archive entière est refusée. Non défini : pas de limite | aucune | **worker-document-process** (`app/config.py`, `app/tasks/import_zip.py`) |
| `ZIP_IMPORT_MAX_TOTAL_BYTES` | Taille maximale d'un ZIP une fois décompressé, en octets ; au-delà, l'archive est refusée (vérifiée sur la taille annoncée puis sur ce qui est réellement lu). Non défini : pas de limite | aucune | idem |
| `ZIP_IMPORT_MAX_FILE_BYTES` | Taille maximale d'un fichier du ZIP, en octets ; un fichier plus gros est ignoré et listé dans le récapitulatif. Non défini : pas de limite | aucune | idem |
| `ZIP_IMPORT_MAX_RATIO` | Taux de compression maximal d'un fichier du ZIP (protection zip bomb, la seule active par défaut : un vrai fichier n'est jamais compressé autant) ; au-delà, le fichier est ignoré | `100` | idem |
| `ZIP_IMPORT_MAX_DEPTH` | Profondeur maximale de dossiers dans un ZIP ; un fichier plus profond est ignoré. Non défini : pas de limite | aucune | idem |
| `TESSDATA_PATH` | Chemin vers les fichiers de données Tesseract, si non standard — le `Dockerfile` du worker le fixe au chemin du paquet apt `tesseract-ocr-fra` | `None` | idem |

## worker/document_process — fichiers tabulaires (#431)

Un fichier tabulaire (CSV, TSV, PSV, XLSX, XLS, ODS, JSON, JSONL, Parquet) est lu en flux, feuille par feuille : le profil
de chaque feuille est calculé en un passage, avec une mémoire bornée quelle que soit la taille du fichier. Ces bornes se
règlent par variables d'environnement du worker d'extraction.

| Variable | Rôle | Défaut |
|---|---|---|
| `TABULAR_MAX_FILE_BYTES` | Taille maximale du fichier, refusé avant d'être téléchargé | `209715200` (200 Mo) |
| `TABULAR_MAX_UNCOMPRESSED_BYTES` | Taille maximale décompressée d'un XLSX/ODS (protège des archives piégées) | `2147483648` (2 Go) |
| `TABULAR_MAX_SHEETS` | Nombre maximal de feuilles lues | `100` |
| `TABULAR_MAX_ROWS_PER_SHEET` | Lignes lues par feuille ; au-delà, la feuille est marquée « tronquée » | `1000000` |
| `TABULAR_MAX_COLUMNS` | Colonnes lues par feuille | `500` |
| `TABULAR_MAX_DISTINCT` | Valeurs distinctes comptées exactement par colonne ; au-delà, le compte est un minorant (« ≥ N ») | `1000` |
| `TABULAR_RESERVOIR_SIZE` | Taille de l'échantillon qui donne la médiane et les quartiles d'une colonne numérique | `2000` |
| `TABULAR_PAGE_MAX_ROWS` | Lignes de chaque feuille reprises dans le texte de la page du document (les données restent entières dans leur copie Parquet) | `10000` |

Les profils des documents indexés avant #431 n'ont qu'une feuille : réindexer le document (#340) donne toutes les feuilles.

## worker/tabular — requêtes SQL sur les données tabulaires (#432)

Image à part (`worker-tabular`), sans modèle : DuckDB sur les copies Parquet des feuilles. Elle partage `REDIS_URL` et
`AWS_*` (une clé en **lecture seule** pour le chart : secret `muffin-s3-readonly`) avec les autres workers.

| Variable | Rôle | Défaut |
|---|---|---|
| `SQL_QUEUE_NAME` | Queue consommée par le pod et à laquelle l'appelant envoie | `tabular_sql` |
| `QUERY_MAX_ROWS` | Lignes rendues par une requête (la requête, elle, peut en lire des millions) ; au-delà, `truncated` | `200` |
| `QUERY_MAX_CELL_CHARS` | Une cellule est coupée à cette longueur | `500` |
| `QUERY_MAX_RESULT_CHARS` | Le résultat est coupé quand son texte atteint cette taille | `200000` |
| `QUERY_TIMEOUT_SECONDS` | Une requête plus longue est interrompue | `30` |
| `QUERY_MEMORY_LIMIT` | Mémoire de DuckDB pour une requête ; au-delà il écrit sur disque, puis la requête échoue (pas le pod) | `512MB` |
| `QUERY_THREADS` | Threads de DuckDB pour une requête | `2` |
| `QUERY_MAX_TABLE_BYTES` | Octets de Parquet téléchargés pour une requête | `524288000` (500 Mo) |
| `CHART_MAX_POINTS` | Lignes de la requête dessinées dans un graphique (elle est rejouée, avec plus de place que ce que l'agent voit) | `5000` |
| `CHART_MAX_CATEGORIES` | Catégories (barres, tranches) au-delà desquelles un graphique n'est pas lisible : on demande d'agréger | `40` |
| `QUERY_MAX_FILES` / `QUERY_MAX_SHEETS` | Fichiers (schémas) et feuilles qu'une requête peut joindre | `10` / `100` |
| `QUERY_WORK_DIR` | Où est fait le dossier privé de chaque requête (le volume inscriptible du pod) | `/tmp` (image) |
| `SQL_TASK_SOFT_TIME_LIMIT_SECONDS` | Limite souple de la tâche, téléchargement compris | `180` |

## worker/layout, worker/ocr, worker/table et worker/vision — pods d'OCR par layout (#406, #407, #410, #411)

Chacun est une image à part (`worker-ocr-layout`, `worker-ocr`, `worker-ocr-table`, `worker-ocr-vision`) avec ses modèles ONNX officiels de PaddlePaddle embarqués.
Ils partagent avec le worker d'extraction `REDIS_URL`, `AWS_*`, `STORAGE_*_TIMEOUT_SECONDS`, le nom de leur queue
(`LAYOUT_QUEUE_NAME` / `OCR_QUEUE_NAME`), `MODELS_DIR`, `OCR_REGION_MIN_SCORE`, `OCR_REGION_MIN_PIXELS`,
`OCR_MAX_REGIONS_PER_PAGE` (layout) et la limite souple de leur tâche : voir plus haut. Propres aux pods :

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `LAYOUT_MODEL_NAME` | Dossier du modèle PP-DocLayoutV3 (export ONNX officiel) sous `MODELS_DIR` | `PP-DocLayoutV3_onnx` | **worker/layout** (`app/config.py`, `app/layout.py`) |
| `LAYOUT_TABLE_MIN_SCORE` | Score minimal d'un **tableau**, plus bas que celui des autres régions : un tableau que le modèle ne voit pas n'est lu par personne (ses cellules ne sont pas une région de texte), un faux tableau ne coûte qu'un recadrage. Un tableau dessiné simplement a été trouvé à 0,46 : à régler sur des documents réels | `0.3` | idem |
| `LAYOUT_DUPLICATE_OVERLAP` | Deux régions dont l'une en recouvre au moins cette part de l'autre sont une seule région vue deux fois : celle au meilleur score reste | `0.9` | idem |
| `OCR_DET_MODEL_NAME` / `OCR_REC_MODEL_NAME` | Dossiers, sous `MODELS_DIR`, du détecteur de texte PP-OCRv5 mobile et du reconnaisseur des écritures latines (accents, ligatures, `œ`, `€`, tirets et apostrophes typographiques) | `PP-OCRv5_mobile_det_onnx` / `latin_PP-OCRv5_mobile_rec_onnx` | **worker/ocr** (`app/config.py`, `app/reader.py`) |
| `OCR_REGION_PADDING_PIXELS` | Pixels ajoutés autour d'une région avant de la lire, pour ne pas couper le bord d'un glyphe | `8` | idem |
| `OCR_CROP_BORDER_PIXELS` | Bordure blanche autour du recadrage lu : sans elle, le détecteur coupe un recadrage très plat (un titre) en morceaux - « Rapport annuel d'activité » sortait en trois lignes, et en une dès 16 pixels | `32` | idem |
| `OCR_LINE_MIN_SCORE` | Score minimal d'une ligne lue ; en dessous, elle est écartée. `0` garde toutes les lignes avec leur score, à l'appelant de juger d'une lecture médiocre | `0.0` | idem |
| `TABLE_MODEL_NAME` | Dossier, sous `MODELS_DIR`, du modèle SLANet_plus (export ONNX officiel) qui lit la structure d'un tableau. Le pod `table` lit aussi le texte des cellules avec les modèles `OCR_DET_MODEL_NAME` / `OCR_REC_MODEL_NAME` du pod `ocr` | `SLANet_plus_onnx` | **worker/table** (`app/config.py`, `app/tables.py`) |
| `TABLE_CROP_MARGIN_PIXELS` | Pixels de la page gardés autour d'un tableau avant de le lire, pour ne pas perdre une bordure que le layout a coupée de près | `8` | idem |
| `TABLE_MAX_CELLS` | Au-delà de ce nombre de cellules, un tableau n'est pas lu (un tableur ne se lit pas sur un scan) et la page retombe sur la lecture de secours | `5000` | idem |
| `TABLE_MAX_PER_PAGE` | Nombre maximal de tableaux lus par page | `20` | idem |
| `ONNX_INTRA_OP_THREADS` | Threads qu'ONNX Runtime peut utiliser pour une page ou une région (`0` : son choix). À régler sur les CPU du pod divisés par la concurrence du worker | `0` | les deux pods |
| `VISION_QUEUE_NAME` | Queue du pod vision | `document_vision` | **worker/vision** (`app/config.py`) et le worker d'extraction |
| `VISION_MODEL_NAME` | Dossier, sous `MODELS_DIR`, de Florence-2 base (poids et code, embarqués dans l'image à une révision figée ; `transformers` est figé, rien n'est téléchargé à l'exécution) | `Florence-2-base` | **worker/vision** (`app/config.py`, `app/florence.py`) |
| `VISION_TASK` | Tâche de Florence-2 demandée : la description détaillée | `<MORE_DETAILED_CAPTION>` | idem |
| `VISION_MAX_NEW_TOKENS` / `VISION_NUM_BEAMS` | Longueur maximale d'une description et largeur de la recherche : bornent le temps d'une image | `128` / `3` | idem |
| `VISION_CROP_MARGIN_PIXELS` | Pixels de la page gardés autour d'une région avant de la décrire | `8` | idem |
| `VISION_MAX_REGIONS` | Régions décrites par page au plus (garde-fou du pod ; le worker d'extraction plafonne plus bas) | `50` | idem |
| `TORCH_THREADS` | Threads de PyTorch pour une inférence (`0` : son choix). À régler sur les CPU du pod divisés par la concurrence (`-c`, 1 par défaut : le modèle pèse environ 2 Go par processus) | `0` | idem |
| `BACKEND_API_URL` / `WORKER_API_KEY` | Le backend, par lequel le pod interroge un modèle du hub qui lit les images (`model` de la tâche autre que Florence-2) : `/api/internal/llm/chat`, la consommation y est enregistrée. Le pod ne porte aucune clé du hub | `http://localhost:8000` / vide | idem (`app/hub.py`) |
| `HUB_TIMEOUT_SECONDS` / `HUB_MAX_TOKENS` | Délai d'un appel au hub et longueur maximale de sa réponse | `120` / `300` | idem |
| `VISION_TASK_SOFT_TIME_LIMIT_SECONDS` | Limite souple de la tâche d'une page | `300` | idem |

## Description des images et des tableaux des pages scannées (#411)

Qui décrit est un réglage **de la collection** (Paramètres → « Description des images ») : `caption_engine` = `local` (le
pod vision, Florence-2, qui répond en anglais ; la description est traduite en français par le modèle de chat du pipeline)
ou `openai` (un modèle du hub qui lit les images, `caption_model`, sinon le premier trouvé par `/api/vision-models`). Le
moteur et le modèle entrent dans l'empreinte de l'extraction (#300) : changer de moteur ne redécrit pas les documents déjà
extraits (pas de rattrapage) ; les ré-extraire les décrit. Variables du **worker d'extraction** :

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `VISION_POD_ENABLED` | Le pod vision est déployé : sans lui, rien n'est décrit, quel que soit le moteur (les deux passent par lui : son modèle, ou un modèle du hub qu'il interroge par le backend). Identique dans les trois pods de l'image, car dans l'empreinte | `false` (chart et compose : `true`) | **worker/document_process** (`app/config.py`, `app/ocr/describe.py`, `app/reuse.py`) |
| `CAPTION_MIN_PIXELS` | Une image n'est décrite que si son petit côté fait au moins ce nombre de pixels de la page | `96` | idem |
| `CAPTION_MAX_PER_PAGE` | Descriptions par page au plus, les plus grandes régions d'abord | `5` | idem |
| `CAPTION_MAX_PER_DOCUMENT` | Descriptions par document au plus. Compté par tâche d'extraction : chaque plage de pages d'un long PDF compte pour elle-même | `50` | idem |
| `CAPTION_TABLES` | Décrire aussi les tableaux lus comme des tableaux (la description va au bout de leur marqueur) | `true` | idem |
| `CAPTION_TRANSLATE` | Traduire en français les descriptions de Florence-2 (un appel au modèle de chat par page, depuis le worker d'extraction) ; sinon elles restent en anglais | `true` | idem |
| `CAPTION_MAX_CHARS` | Longueur maximale d'une description dans le texte de la page (coupée à un mot) | `600` | idem |
| `CAPTION_STAGE_TIMEOUT_SECONDS` | Temps accordé aux descriptions d'une page. Passé ce délai, la page est gardée **sans** elles, sans repasser par la lecture de secours | `300` | idem |

## backend — l'agent de recherche (`app/agent/config.py`)

Ces variables bornent le graphe LangGraph de recherche (§28 du brief d'architecture) pour qu'une
requête pathologique ne puisse pas faire tourner indéfiniment le fan-out. L'agent tourne dans le backend, en tâche de fond.

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `MAX_CONCURRENT_RUNS` | Runs qu'un pod du backend exécute en même temps (une tâche asyncio chacune) ; les autres attendent, en file | `8` | **backend** (`app/agent/config.py`, `app/agent/runner.py`) |
| `MAX_PARALLEL_TASKS` | Nombre max de requêtes du plan exécutées en parallèle (fan-out `Send`) | `4` | idem (`graph/routing/conditions.py`) |
| `MAX_TOTAL_TASKS` | Plafond cumulé de tâches sur toute la durée d'un run | `12` | idem |
| `GATE_MIN_EVIDENCE` | Passages d'une recherche de contenu qui suffisent pour écrire une réponse (le `gate`, sans modèle) ; en dessous, la recherche est élargie à toutes les collections une fois | `1` | idem (`graph/nodes/gate.py`) |
| `GATE_MIN_SCORE` | Score en dessous duquel un passage ne compte pas pour le `gate` (0 : tout passage compte, à calibrer sur de vraies questions) | `0.0` | idem |
| `SQL_QUEUE_NAME` | Queue du worker de requêtes SQL (`worker/tabular`, #432) à laquelle l'outil `tabular_query` envoie ses requêtes (#433) | `tabular_sql` | idem (`app/agent/graph/services/tabular_worker.py`) |
| `TABULAR_MAX_STEPS` | Appels de `query_data` qu'une tâche `tabular_query` peut enchaîner avant d'être invitée à conclure | `8` | idem |
| `TABULAR_QUERY_TIMEOUT_SECONDS` | Attente de la réponse du worker pour une requête ; au-delà, la tâche échoue avec un message clair | `120` | idem |
| `TABULAR_POLL_SECONDS` | Intervalle entre deux regards sur le résultat (la révocation est regardée à chaque fois) | `0.3` | idem |
| `TABULAR_MAX_FILES` | Fichiers qu'une tâche peut interroger (la limite `QUERY_MAX_FILES` du worker) ; les autres sont signalés | `10` | idem |
| `TABULAR_MAX_CHARTS` | Graphiques qu'une réponse peut porter (le backend en refuse davantage) | `6` | idem |
| `TABULAR_CHART_TIMEOUT_SECONDS` | Attente du dessin d'un graphique par le worker | `90` | idem |
| `TABULAR_MAX_CATEGORIES_HINT` | Nombre de catégories que le modèle est invité à ne pas dépasser (à aligner sur `CHART_MAX_CATEGORIES`) | `40` | idem |
| `TABULAR_PROMPT_ROWS` / `TABULAR_EVIDENCE_ROWS` | Lignes d'un résultat relues par le modèle / gardées dans la preuve sous la réponse | `50` / `100` | idem |

L'agent n'exécute plus de SQL ni ne lit de fichier : il n'a plus de variables `AWS_*` ni de DuckDB (#433).
| `MAX_QUESTION_ROUNDS` | Nombre max de fois de suite où l'assistant pose des questions à choix avant de poursuivre avec des hypothèses qu'il énonce (#344) | `2` | idem (`graph/nodes/plan.py`) |
| `SEARCH_RESULTS_PER_QUERY` | Nombre de résultats retournés par recherche vectorielle | `5` | idem |

Délégation d'une modification de document vivant à l'agent d'édition (#171) :

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `EDIT_WAIT_SECONDS` | Durée maximale pendant laquelle un run attend que l'agent d'édition ait fini une modification déléguée. Passé ce délai, la réponse dit que la proposition apparaîtra dans la carte du chat | `300` | idem (`graph/nodes/delegate_edit.py`) |
| `EDIT_POLL_SECONDS` | Intervalle entre deux interrogations du backend sur l'état du brouillon pendant cette attente | `2.0` | idem |

## backend — garde-fous sur la saisie (#516)

Ce que définit l'administrateur (quels garde-fous, leur mode, leur étape, la politique) est stocké dans l'application (`/admin/guardrails`, voir `docs/guardrails.md`) ; ces variables sont les bornes qu'aucun réglage ne lève.

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `GUARDRAILS_TEXT_MAX_CHARS` | Longueur maximale du texte présenté à un garde-fou (le reste n'est ni lu par un modèle ni envoyé à un service) | `20000` | **backend** (`app/config/guardrails.py`) |
| `GUARDRAILS_PATTERN_MAX_CHARS` | Longueur maximale d'un motif d'un garde-fou de type `rules` | `500` | idem |
| `GUARDRAILS_PATTERNS_MAX` | Nombre maximal de motifs d'un garde-fou | `50` | idem |
| `GUARDRAILS_TERMS_MAX` | Nombre maximal de termes d'un garde-fou | `2000` | idem |
| `GUARDRAILS_MAX` | Nombre maximal de garde-fous | `50` | idem |
| `GUARDRAILS_TIMEOUT_LIMIT_MS` | Plus longue attente (ms) qu'un administrateur peut donner à un garde-fou ou à l'ensemble | `30000` | idem |
| `GUARDRAILS_ALLOWED_PRIVATE_HOSTS` | Hôtes (séparés par des virgules) qu'un garde-fou `http` peut appeler bien qu'ils soient sur un réseau privé ; rien d'autre qui ne soit public n'est joint | vide | idem |
| `GUARDRAILS_RESULTS_RETENTION_DAYS` | Durée de conservation (jours) des verdicts et des comptes — jamais du texte | `180` | idem (purge de la maintenance des routines) |

## backend — mémoire de l'utilisateur (#282)

Ce que la personne retient ou non est à elle (page « Ma mémoire », voir `docs/memory.md`) ; ces variables sont les bornes de l'application et l'interrupteur de l'administrateur.

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `MEMORY_ENABLED` | Coupe-circuit : à `false`, rien n'est lu, retenu ni signalé comme utilisé, pour tout le monde ; ce qui est enregistré reste | `true` | **backend** (`app/config/memory.py`) |
| `MEMORY_VALUE_MAX_CHARS` | Longueur maximale d'une phrase retenue | `300` | idem |
| `MEMORY_MAX_ITEMS` | Nombre maximal d'éléments par personne | `100` | idem |
| `MEMORY_PROMPT_MAX_CHARS` | Ce qu'un run lit au plus de la mémoire (≈ 4 caractères par jeton, soit ~500 jetons) ; le reste n'entre pas dans le prompt | `2000` | idem |

## worker/evaluation — évaluation du retrieval (issue #11)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker | `evaluation` | **worker/evaluation** (`app/config.py`) |
| `DEFAULT_TOP_K` | Nombre de chunks retrouvés par question quand `k` n'est pas explicitement passé à la tâche | `5` | idem (`app/tasks.py`) |

## worker/document_edit — édition de documents vivants (issue #167)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker - doit correspondre à `DOCUMENT_EDIT_QUEUE` de `backend/app/core/tasks.py` | `document_edit` | **worker/document_edit** (`app/config.py`) |
| `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_BUCKET` | Accès RustFS pour lire le fichier source et écrire le brouillon (mêmes variables et mêmes défauts que `worker/document_process`) | voir plus haut | idem (`app/storage.py`) |
| `EDIT_LLM_MODEL` | Modèle de chat qui planifie l'édition. Vide : le modèle de chat par défaut du hub LLM (`/internal/llm/default-chat-model`) | `""` | idem (`app/tasks.py`) |
| `EDIT_MAX_TOKENS` | Longueur maximale de la réponse du modèle (la liste d'opérations, pas un document réécrit) | `4096` | idem |
| `EDIT_MAX_ATTEMPTS` | Nombre de fois où le modèle est rappelé en lui montrant pourquoi sa réponse précédente a été refusée (JSON invalide, opération visant une section inexistante...). Passé ce nombre, la tâche échoue avec le dernier motif | `3` | idem (`app/agent.py`) |
| `SOFFICE_BIN` | Binaire LibreOffice qui convertit un brouillon ODT en PDF d'aperçu (#169). Chaque conversion tourne avec son propre profil (`-env:UserInstallation`) | `soffice` | idem (`app/preview.py`) |
| `PREVIEW_TIMEOUT_SECONDS` | Durée maximale d'une conversion ODT → PDF avant qu'elle soit abandonnée (la tâche échoue alors avec un message clair) | `120` | idem |
| `EDIT_MAX_OUTLINE_CHARS` | Taille maximale (en caractères) du plan du document envoyé au modèle. Au-delà, la tâche échoue avec un message clair plutôt que d'éditer à l'aveugle | `60000` | idem |

## worker/owui_sync — synchronisation Open WebUI → Muffin (#453)

Un worker à part (image `worker-owui-sync`, queue `owui_sync`) lit Open WebUI par son API REST et copie dans Muffin, par le backend, ses
groupes, ses knowledge bases et leurs partages en lecture, ses fichiers et leurs chunks. Rien d'autre n'est copié : les fichiers restent
dans le bucket qu'ils partagent et les vecteurs dans ses collections Qdrant. Il partage `REDIS_URL`, `BACKEND_API_URL`, `WORKER_API_KEY` et les
réglages de logs avec les autres workers. Propres à ce worker :

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Sa queue, la même que `OWUI_SYNC_QUEUE` du backend | `owui_sync` | **worker/owui_sync** |
| `OWUI_BASE_URL` | Adresse d'Open WebUI | `http://localhost:3001` | **worker/owui_sync** |
| `OWUI_API_KEY` | Clé d'API d'un administrateur d'Open WebUI (lecture seule) | — | **worker/owui_sync** |
| `AWS_BUCKET` | Le bucket de Muffin, partagé avec Open WebUI : un fichier qui y est garde la clé qu'Open WebUI lui a donnée | `muffin-documents` | **worker/owui_sync** |
| `OWUI_SYNC_INTERVAL_MINUTES` | Intervalle du beat (`celery beat`, un processus à part). `0` : aucune synchronisation planifiée, seulement `POST /api/admin/owui-sync` ou le CronJob Helm | `60` | **worker/owui_sync** |
| `ENRICHMENT_QUEUE_NAME` / `SUMMARY_PRIORITY` | La file du worker d'enrichissement (`document_enrichment`) et la priorité (`9`, la plus basse) avec lesquelles il envoie le résumé d'un fichier copié et la mise à jour de la description de sa collection (#457). Ils suivent `DOCUMENT_ENRICHMENT_QUEUE` et `BULK_PRIORITY` du backend | `document_enrichment` / `9` | **worker/owui_sync** |
| `QDRANT_URL` / `QDRANT_API_KEY` | Le Qdrant d'Open WebUI, le même que celui de Muffin | `http://localhost:6333` / — | **worker/owui_sync** |
| `OWUI_QDRANT_PREFIX` | Préfixe des collections d'Open WebUI (son `QDRANT_COLLECTION_PREFIX`, mode classique) : la knowledge base `X` est dans `<préfixe>_X`. À régler de la même façon côté backend, qui lit ces collections pour chercher | `open-webui` | **worker/owui_sync**, **backend** |

Le bucket S3 est **partagé** avec Open WebUI : `AWS_BUCKET` du worker (et des autres services de Muffin) est celui que `S3_BUCKET_NAME`
désigne côté Open WebUI, avec les mêmes accès. Un fichier copié garde la clé qu'Open WebUI lui a donnée, telle quelle (`<id>_<nom>`
à la racine du bucket s'il n'y a pas de préfixe, `<préfixe>/<id>_<nom>` s'il y en a un) : Muffin n'y ajoute ni n'y retire rien, et ne
supprime jamais le fichier d'un document copié (ni en supprimant le document, ni la collection). Un fichier d'un autre bucket garde
la forme `s3://<bucket>/<clé>` et n'est lu que par le backend. Les utilisateurs et groupes d'Open WebUI doivent se connecter par le
Keycloak de Muffin : un membre se retrouve par son `sub` (`oauth.oidc.sub`), et celui qui n'en a pas est laissé de côté.

### Cohérence des vecteurs

À chaque synchronisation d'une knowledge base, le worker compare ce qu'Open WebUI a stocké à ce que Muffin utilisera pour chercher :

- les modèles que disent les chunks (`metadata.embedding_config`, sur un échantillon de 100) et celui qu'Open WebUI a configuré;
- la longueur du vecteur de sa collection Qdrant et celle que donne le modèle (apprise une fois par modèle, par un embedding d'un mot
  par le hub de Muffin; si le hub ne répond pas, la longueur n'est pas vérifiée);
- que la collection existe, pour une knowledge base qui a des fichiers.

Un écart est un avertissement dans les logs, `vector_problems` dans le résultat de la tâche et `inconsistent` dans le bilan de la
synchronisation (`finish_sync`) : il ne bloque pas la copie. La cause usuelle est un changement de modèle côté Open WebUI : il faut alors
ré-embedder ses fichiers.

### Déploiement Helm

Désactivé tant qu'aucun Open WebUI ne lui est donné : KEDA le garde à 0 pod quand sa queue est vide et le CronJob `owui-sync`, qui y met la
tâche racine toutes les heures (`schedule`), est suspendu. Pour l'activer :

1. créer le secret `muffin-owui-sync` avec `OWUI_BASE_URL` et `OWUI_API_KEY` ;
2. régler `OWUI_QDRANT_PREFIX` côté worker (`worker_owui_sync.env`) **et** côté backend (`backend.env`) s'il n'est pas `open-webui` ;
3. mettre `cronjobs.owui-sync.suspend: false` (ou lancer une synchronisation à la main par `POST /api/admin/owui-sync`).

Le beat embarqué (`OWUI_SYNC_INTERVAL_MINUTES`) n'est pas déployé par Helm : le CronJob fait le même travail sans processus à surveiller.

## Frontend (Vite)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `VITE_API_BASE_URL` | URL de base de l'API backend appelée depuis le navigateur | `http://localhost:8000` (fallback en dur dans chaque composable si la variable est absente) | **frontend** — tous les composables faisant du `fetch` (`useChat.ts`, `useCollections.ts`, `useTasks.ts`, `useCurrentUser.ts`, `useModels.ts`, `useEmbeddingModels.ts`, `useAdminSettings.ts`) et les modals qui chargent des ressources (`SourceDocumentModal.vue`, `DocumentDetailModal.vue`) |
| `VITE_DISABLE_RUN_STREAM` | `true` pour que le chat suive les runs par interrogation au lieu du flux en direct (#510) : utile derrière un proxy qui ne laisse pas passer `text/event-stream` | absente (flux actif) | **frontend** — `useChat.ts` (lue au build) |

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
