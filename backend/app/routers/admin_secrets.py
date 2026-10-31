from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_store import SecretStoreError, get_provider
from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.secret_store import RewrapOut, SecretsStatusOut
from app.services.secret_store_service import SecretStore

router = APIRouter(prefix="/admin/secrets", tags=["Admin"])


def require_admin(user: Annotated[RequestContext, Depends(get_current_user)]) -> RequestContext:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


AdminDep = Annotated[RequestContext, Depends(require_admin)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/status",
    summary="Where the stored secrets are encrypted, and how far a rotation of the key has got",
    response_model=SecretsStatusOut,
)
async def secrets_status(_: AdminDep, db: DbDep) -> SecretsStatusOut:
    store = SecretStore(db)
    versions = await store.versions()
    try:
        provider = get_provider()
        current = await provider.current_version()
    except SecretStoreError:
        logger.warning("The secret provider cannot be reached or is not configured", exc_info=True)
        return SecretsStatusOut(
            provider="unavailable",
            reachable=False,
            current_version=None,
            versions=versions,
            stale=sum(versions.values()),
        )
    return SecretsStatusOut(
        provider=provider.name,
        reachable=True,
        current_version=current,
        versions=versions,
        stale=sum(count for version, count in versions.items() if version != current),
    )


@router.post(
    "/rewrap",
    summary="Bring the secrets made with an older version of the key to the latest one, a batch at a time",
    response_model=RewrapOut,
)
async def rewrap_secrets(_: AdminDep, db: DbDep, limit: int = 200) -> RewrapOut:
    try:
        progress = await SecretStore(db).rewrap_batch(max(1, min(limit, 1000)))
    except SecretStoreError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The secret provider is not available") from error
    await db.commit()
    logger.info(f"{progress.rewrapped} secret(s) rewrapped to {progress.current_version}, {progress.remaining} left")
    return RewrapOut(
        rewrapped=progress.rewrapped, remaining=progress.remaining, current_version=progress.current_version
    )
