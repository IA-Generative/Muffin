import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import WorkerSettings

# Exposed as a module attribute (rather than closed over) so tests can swap
# it out with monkeypatch.setattr without a real WORKER_API_KEY configured.
_worker_settings = WorkerSettings()

# APIKeyHeader rather than a plain Header(): registers X-API-Key as an OpenAPI
# security scheme so Swagger UI's "Authorize" button can set it. auto_error=False
# keeps the missing-key case falling through to the hmac check below (which raises
# with the same 401 either way), instead of FastAPI rejecting it earlier with a
# less specific error.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
_api_key_security = Security(api_key_scheme)

# The OpenAI wire format authenticates with "Authorization: Bearer <key>" - what
# promptfoo's openai provider (the evaluation judge)
# sends. HTTPBearer rather than a plain Header() for the same OpenAPI-registration
# reason as above; auto_error=False for the same fall-through reason.
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_security = Security(_bearer_scheme)


def require_worker_api_key(x_api_key: str | None = _api_key_security) -> None:
    # hmac.compare_digest, not `==`: a plain comparison leaks how many
    # leading characters matched through response timing.
    if not _worker_settings.WORKER_API_KEY or not hmac.compare_digest(x_api_key or "", _worker_settings.WORKER_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


def require_worker_bearer_key(credentials: HTTPAuthorizationCredentials | None = _bearer_security) -> None:
    """Same check as require_worker_api_key, reading the Bearer token instead of
    X-API-Key - for OpenAI-compatible callers that can't be told to send a custom
    header (promptfoo's judge provider)."""
    if not _worker_settings.WORKER_API_KEY or not hmac.compare_digest(
        credentials.credentials if credentials else "", _worker_settings.WORKER_API_KEY
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
