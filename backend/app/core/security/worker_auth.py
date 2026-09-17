import hmac

from fastapi import Header, HTTPException, status

from app.config import WorkerSettings

# Exposed as a module attribute (rather than closed over) so tests can swap
# it out with monkeypatch.setattr without a real WORKER_API_KEY configured.
_worker_settings = WorkerSettings()


def require_worker_api_key(x_api_key: str = Header(default="")) -> None:
    # hmac.compare_digest, not `==`: a plain comparison leaks how many
    # leading characters matched through response timing.
    if not _worker_settings.WORKER_API_KEY or not hmac.compare_digest(x_api_key, _worker_settings.WORKER_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
