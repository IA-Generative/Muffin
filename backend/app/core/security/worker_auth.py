import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

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


def require_worker_api_key(x_api_key: str | None = _api_key_security) -> None:
    # hmac.compare_digest, not `==`: a plain comparison leaks how many
    # leading characters matched through response timing.
    if not _worker_settings.WORKER_API_KEY or not hmac.compare_digest(x_api_key or "", _worker_settings.WORKER_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
