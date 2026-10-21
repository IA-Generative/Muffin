import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.document_revision import RevisionOrigin
from app.models.run import Run
from app.repositories.run_repository import RunRepository
from app.schemas.document import DocumentOut
from app.services.living_document_service import LivingDocumentService
from app.services.run_service import RunNotFoundError


class NoPendingCreationError(Exception):
    """The run proposed no document, or the proposal was already created or refused."""


class CreationProposalService:
    """A Markdown document the research agent wrote and proposed to create in a collection. It lives
    in the run (`Run.edit_proposal`, kind "create") until the user decides: nothing exists in the
    collection before they validate, and validating goes through the same checks as creating a
    document by hand (the collection must be one they may edit)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = RunRepository(db)

    async def validate(self, run_id: uuid.UUID, user: RequestContext) -> DocumentOut:
        run, proposal = await self._pending(run_id, user)
        document = await LivingDocumentService(self.db).create_markdown(
            uuid.UUID(proposal["collection_id"]),
            user,
            proposal["name"],
            proposal["content"],
            origin=RevisionOrigin.CHAT,
        )
        # A new dict: a JSONB column only notices a reassignment, not an edit made in place.
        run.edit_proposal = {**proposal, "status": "created", "document_id": str(document.id)}
        await self.db.commit()
        return document

    async def refuse(self, run_id: uuid.UUID, user: RequestContext) -> None:
        run, proposal = await self._pending(run_id, user)
        run.edit_proposal = {**proposal, "status": "refused"}
        await self.db.commit()

    async def _pending(self, run_id: uuid.UUID, user: RequestContext) -> tuple[Run, dict[str, Any]]:
        run = await self.runs.get(run_id, user.user_id)
        if run is None:
            raise RunNotFoundError(str(run_id))
        proposal = run.edit_proposal
        if not proposal or proposal.get("kind") != "create" or proposal.get("status") != "pending":
            raise NoPendingCreationError(str(run_id))
        return run, proposal
