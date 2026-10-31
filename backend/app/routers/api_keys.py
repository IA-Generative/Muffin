import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services.api_key_service import (
    ApiKeyNotFoundError,
    ApiKeysDisabledError,
    ApiKeyService,
    InvalidApiKeyRequestError,
    TooManyApiKeysError,
)

# Managed with a session or a Keycloak token, never with a key: a key cannot make or revoke keys.
router = APIRouter(prefix="/api-keys", tags=["API keys"])


def get_api_key_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ApiKeyService:
    return ApiKeyService(db)


ServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "", summary="The user's own API keys, newest first - never the keys themselves", response_model=list[ApiKeyOut]
)
async def list_api_keys(user: UserDep, service: ServiceDep) -> list[ApiKeyOut]:
    return [ApiKeyOut.model_validate(key, from_attributes=True) for key in await service.list_keys(user)]


@router.post(
    "",
    summary="Make an API key. The key is in the answer and nowhere else: it cannot be read again",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreated,
)
async def create_api_key(body: ApiKeyCreate, user: UserDep, service: ServiceDep, response: Response) -> ApiKeyCreated:
    try:
        row, key = await service.create(user, body)
    except ApiKeysDisabledError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API keys are not enabled") from error
    except InvalidApiKeyRequestError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except TooManyApiKeysError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many API keys: revoke one first") from error
    # A secret: not to be kept by a browser or a proxy.
    response.headers["Cache-Control"] = "no-store"
    return ApiKeyCreated(**ApiKeyOut.model_validate(row, from_attributes=True).model_dump(), key=key)


@router.delete("/{key_id}", summary="Revoke an API key at once", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, user: UserDep, service: ServiceDep) -> Response:
    try:
        await service.revoke(user, key_id)
    except ApiKeyNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
