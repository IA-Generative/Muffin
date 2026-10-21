import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_draft import DocumentDraft, DraftStatus


class DocumentDraftRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_document(self, document_id: uuid.UUID) -> DocumentDraft | None:
        result = await self.db.execute(select(DocumentDraft).where(DocumentDraft.document_id == document_id))
        return result.scalar_one_or_none()

    async def get_by_celery_id(self, celery_task_id: str) -> DocumentDraft | None:
        result = await self.db.execute(select(DocumentDraft).where(DocumentDraft.celery_task_id == celery_task_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        document_id: uuid.UUID,
        *,
        base_revision: int,
        format_: str,
        prompt: str,
        user_id: str,
        user_display: str | None,
        celery_task_id: str | None,
        lock_token: str,
        origin: str = "chat",
        filename: str | None = None,
        draft_storage_key: str | None = None,
        status: DraftStatus = DraftStatus.PENDING,
        job_kind: str = "edit",
        edited: bool = False,
        operations_summary: str = "",
    ) -> DocumentDraft:
        draft = DocumentDraft(
            document_id=document_id,
            base_revision=base_revision,
            format=format_,
            status=status,
            job_kind=job_kind,
            origin=origin,
            filename=filename,
            draft_storage_key=draft_storage_key,
            edited=edited,
            operations_summary=operations_summary,
            prompt=prompt,
            requested_by_user_id=user_id,
            requested_by_display=user_display,
            celery_task_id=celery_task_id,
            lock_token=lock_token,
            pending_images=[],
        )
        self.db.add(draft)
        await self.db.flush()
        return draft

    async def delete(self, draft: DocumentDraft) -> None:
        await self.db.delete(draft)

    @staticmethod
    def storage_keys(draft: DocumentDraft) -> list[str]:
        """Every RustFS object a draft owns - its file, its preview and the images uploaded for it."""
        images: list[dict[str, Any]] = draft.pending_images or []
        keys = [
            draft.draft_storage_key,
            draft.preview_pdf_key,
            draft.base_preview_pdf_key,
            *(image.get("storage_key") for image in images),
        ]
        return [key for key in dict.fromkeys(keys) if key]
