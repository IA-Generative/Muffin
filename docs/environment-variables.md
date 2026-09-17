# Environment variables

Which file to put a value in depends on how you're running the service:

| File | Read by | When |
| --- | --- | --- |
| `.env` (repo root, gitignored) | `docker compose` | Always, for `make up` / `make down` |
| `backend/.env.local` (gitignored) | the backend app (pydantic-settings) | Running the backend outside Docker via `make back` |
| `tests/.env.testing` (tracked) | pytest, via `pytest-dotenv` | `make test-backend` / CI |

`backend/.env.local` overrides `backend/.env` if both exist; neither is required — every
setting below has a built-in default. A real environment variable (e.g. one exported by
Docker Compose or CI) always wins over anything in a `.env*` file.

## Keycloak (`backend/app/config/keycloak.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `KEYCLOAK_URL` | `http://localhost:8080` | Backend-to-Keycloak URL (Docker service name inside the stack, e.g. `http://keycloak:8080`) |
| `KEYCLOAK_PUBLIC_URL` | falls back to `KEYCLOAK_URL` | Browser-facing Keycloak URL, if different (e.g. behind a reverse proxy) |
| `KEYCLOAK_REALM` | `muffin` | Realm name |
| `KEYCLOAK_CLIENT_ID` | `muffin-backend` | Confidential client ID |
| `KEYCLOAK_CLIENT_SECRET` | _(none)_ | Client secret — required for a real login flow |
| `BACKEND_PUBLIC_URL` | `http://localhost:8000` | Used to build the OAuth2 `redirect_uri` registered on the Keycloak client |
| `FRONTEND_URL` | `http://localhost:5173` | Where the browser lands after login/logout; also the single allowed CORS origin |
| `SESSION_COOKIE_NAME` | `muffin_session` | BFF session cookie name |
| `SESSION_COOKIE_SECURE` | `true` | Set to `false` for local HTTP (no TLS) |
| `SESSION_COOKIE_SAMESITE` | `lax` | `lax` \| `strict` \| `none` |
| `SESSION_TTL_SECONDS` | `604800` (7 days) | Server-side session lifetime in Redis |

## Database (`backend/app/config/database.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://muffin:muffin@localhost:5432/muffin` | Async SQLAlchemy connection string |

## Redis (`backend/app/config/redis.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | Sessions, pending-auth state, and the chat-models cache |

## LLM hub (`backend/app/config/llm.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | _(empty)_ | API key for the OpenAI-compatible LLM hub |
| `OPENAI_API_BASE_URL` | _(empty)_ | Base URL of that hub. Left unset, `GET /api/models` responds `503` instead of silently calling the public OpenAI API |
| `CHAT_MODELS_CACHE_TTL_SECONDS` | `3600` | How long the discovered chat-capable model list is cached in Redis |

## Logging (`backend/app/config/logging.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | loguru log level |
| `LOG_FORMAT` | `console` | `console` (colorized) or `json` |

## Worker API key (`backend/app/config/worker.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `WORKER_API_KEY` | _(empty)_ | Shared secret checked (via the `X-API-Key` header) on every `/api/internal/*` call from a worker. Empty means those routes always respond `401` |

## Auth strategy (read directly from `os.environ`, not a `.env` file)

| Variable | Default | Description |
| --- | --- | --- |
| `VERIFY_TOKEN_MODEL` | `keycloak` | `keycloak` (real) or `full-access` (fixed dev identity, no Keycloak/Redis — used by tests/CI) |

## Docker Compose only (repo-root `.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:8081` | Passed through to the `backend` service. Set to `http://localhost:5173` when running the frontend via `make front` instead of the dockerized `frontend` service |
| `OPENAI_API_KEY` / `OPENAI_API_BASE_URL` | _(empty)_ | Same as above, passed through to the dockerized `backend` service |
| `WORKER_API_KEY` | `dev-only-worker-key-not-for-prod` | Shared between `backend` and `worker-document-process`; passed through to both |

## Document-processing worker (`worker/document_process/app/config.py`)

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/result backend |
| `CELERY_QUEUE_NAME` | `document_processing` | Dedicated queue this worker consumes from |
| `BACKEND_API_URL` | `http://localhost:8000` | Base URL for `/api/internal/*` calls |
| `WORKER_API_KEY` | _(empty)_ | Must match the backend's `WORKER_API_KEY` |
| `RUSTFS_ENDPOINT_URL` | `http://localhost:9000` | RustFS S3 API endpoint |
| `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` | `rustfsadmin` / `rustfsadmin` | RustFS credentials (dev defaults — change for anything real) |
| `RUSTFS_BUCKET` | `muffin-documents` | Bucket holding uploaded files and generated page screenshots |
| `OCR_LANGUAGE` | `fra` | Tesseract language code liteparse uses for scanned pages |
| `TESSDATA_PATH` | _(none)_ | Where to find that language's `.traineddata` file — the Docker image sets this to the apt-installed `tesseract-ocr-fra` path |

## Frontend (`frontend/.env*`, read by Vite - `VITE_` prefix required)

| Variable | Default | Description |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL the frontend calls for the backend API |
