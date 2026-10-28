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
| `REDIS_URL` | URL Redis (broker ET result backend Celery, aussi utilisé comme checkpointer LangGraph côté agent_execution) | `redis://localhost:6379/0` | **backend** (`app/config/redis.py` → `app/core/tasks.py`, producteur Celery), **worker/document_process**, **worker/agent_execution**, **worker/evaluation**, **worker/document_edit** (`app/config.py`, chacun avec sa propre queue) |

Le broker est un unique `redis-stack-server` partagé ; chaque worker consomme ses propres queues
Celery sur ce même Redis (`document_extraction`, `document_enrichment`, `document_import`,
`index_rebuild` pour worker/document_process, voir son README ; `agent_execution`, `evaluation`,
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

Les workers n'accèdent jamais directement à Qdrant : toute recherche/écriture vectorielle
passe par les endpoints internes du backend (`/internal/search`, `/internal/qa-search`,
`/internal/summary-search`, `/internal/pipeline/*`).

Le conteneur **qdrant** lui-même lit `QDRANT__SERVICE__API_KEY` (docker-compose : la valeur de `QDRANT_API_KEY`, par défaut
`dev-only-qdrant-key-not-for-prod` ; Helm : le secret Vault `muffin-qdrant`).

## Recherche web (SearXNG)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `SEARXNG_URL` | URL de l'instance SearXNG | `http://localhost:8080` | **worker/agent_execution** (`app/config.py` → `app/searxng_client.py`) |

Contrairement à Qdrant/Postgres, c'est le worker `agent_execution` qui appelle SearXNG
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
| `WORKER_API_KEY` | Secret partagé, vérifié sur chaque appel `/internal/*` par `app/core/security/worker_auth.py` (dépendance `require_worker_api_key`) | `""` côté backend / `""` côté workers | **backend** (`app/config/worker.py`), **worker/document_process**, **worker/agent_execution**, **worker/evaluation**, **worker/document_edit** — doit être identique des deux côtés, sinon tout appel interne échoue en 401 |

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

## Backend ↔ workers (URLs)

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `BACKEND_API_URL` | URL du backend vue par les workers, base de tous leurs appels `/internal/*` | `http://localhost:8000` | **worker/document_process**, **worker/agent_execution**, **worker/evaluation**, **worker/document_edit** (`app/config.py` → clients HTTP `backend_client.py`) |

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

## worker/layout et worker/ocr — pods d'OCR par layout (#406, #407)

Chacun est une image à part (`worker-ocr-layout`, `worker-ocr`) avec son modèle ONNX officiel de PaddlePaddle embarqué.
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
| `ONNX_INTRA_OP_THREADS` | Threads qu'ONNX Runtime peut utiliser pour une page ou une région (`0` : son choix). À régler sur les CPU du pod divisés par la concurrence du worker | `0` | les deux pods |

## worker/agent_execution — budgets d'exécution de l'agent

Ces variables bornent le graphe LangGraph de recherche (§28 du brief d'architecture) pour qu'une
requête pathologique ne puisse pas faire tourner indéfiniment le fan-out ou la
boucle de vérification (« grounding »).

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `CELERY_QUEUE_NAME` | Nom de la queue Celery consommée par ce worker | `agent_execution` | **worker/agent_execution** (`app/config.py`) |
| `MAX_PARALLEL_TASKS` | Nombre max de tâches de recherche exécutées en parallèle (fan-out `Send`) | `4` | idem (`graph/routing/conditions.py`) |
| `MAX_PARALLEL_SEARCHES` | Nombre max de recherches vectorielles en parallèle au sein d'une tâche | `4` | idem |
| `MAX_TOTAL_TASKS` | Plafond cumulé de tâches sur toute la durée d'un run | `12` | idem |
| `MAX_TOTAL_SEARCHES` | Plafond cumulé de recherches sur toute la durée d'un run | `20` | idem |
| `MAX_GROUNDING_RESEARCHES` | Nombre max de relances de recherche déclenchées par un échec de vérification (grounding) | `1` | idem |
| `MAX_QUESTION_ROUNDS` | Nombre max de fois de suite où l'assistant pose des questions à choix avant de poursuivre avec des hypothèses qu'il énonce (#344) | `2` | idem (`graph/nodes/request_clarification.py`) |
| `SEARCH_RESULTS_PER_QUERY` | Nombre de résultats retournés par recherche vectorielle | `5` | idem |
| `MAX_ROUTED_COLLECTIONS` | Nombre max de collections retenues par le routage pour une tâche de recherche, dès qu'il existe des sous-collections ; au-delà, l'agent propose à l'utilisateur d'aller plus loin | `15` | idem |

Délégation d'une modification de document vivant à l'agent d'édition (#171) :

| Variable | Définition | Défaut | Utilisée par |
|---|---|---|---|
| `EDIT_WAIT_SECONDS` | Durée maximale pendant laquelle un run attend que l'agent d'édition ait fini une modification déléguée. Passé ce délai, la réponse dit que la proposition apparaîtra dans la carte du chat | `300` | idem (`graph/nodes/delegate_edit.py`) |
| `EDIT_POLL_SECONDS` | Intervalle entre deux interrogations du backend sur l'état du brouillon pendant cette attente | `2.0` | idem |

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
