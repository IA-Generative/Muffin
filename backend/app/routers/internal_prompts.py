import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import redis_connector
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.prompt_repository import PromptRepository
from app.schemas.prompt import ActivePromptOut, RunPromptUsagesCreate

router = APIRouter(
    prefix="/internal/prompts",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)

# Short TTL (not the hour-long one models.py/internal_llm.py use for model discovery): an admin
# publishing a new prompt version should reach running workers reasonably fast, not just on
# their next restart.
_CACHE_TTL_SECONDS = 60


@router.get("/{name}/active", summary="The currently active version of one of the agent's prompts")
async def get_active_prompt(name: str, db: Annotated[AsyncSession, Depends(get_db)]) -> ActivePromptOut:
    cache_key = f"prompts:active:{name}"
    cached = redis_connector.client.get(cache_key)
    if cached is not None:
        return ActivePromptOut(**json.loads(cached))

    prompt = await PromptRepository(db).get_active(name)
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No active prompt named '{name}'")

    out = ActivePromptOut.model_validate(prompt)
    redis_connector.client.set(cache_key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    return out


@router.post("/runs/{run_id}/usages", summary="Record which prompt versions a run actually used")
async def record_run_prompt_usages(
    run_id: uuid.UUID, update: RunPromptUsagesCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    repository = PromptRepository(db)
    await repository.record_usages(run_id, update.prompt_version_ids)
    await db.commit()
