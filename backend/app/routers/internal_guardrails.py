import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.schemas.guardrail import RunGuardrailOut
from app.services.guardrail_service import GuardrailService

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


@router.post(
    "/runs/{run_id}/guardrails",
    summary="The guardrails on the input: what they decide for the request of a run, before any model reads it (#516)",
)
async def check_run(run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> RunGuardrailOut:
    decision = await GuardrailService(db).evaluate_run(run_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return decision
