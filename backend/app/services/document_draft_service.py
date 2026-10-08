import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import EDIT_DOCUMENT_TASK, INSERT_IMAGES_TASK, enqueue_edit_document, enqueue_insert_images
from app.models.document import Document
from app.models.document_draft import DocumentDraft, DraftStatus
from app.models.document_revision import RevisionOrigin
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_draft_repository import DocumentDraftRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.document_revision_repository import DocumentRevisionRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.document import DocumentLockOut, DocumentOut
from app.schemas.document_draft import DraftOut, DraftResultIn
from app.services.living_document_service import (
    FORMAT_MEDIA_TYPES,
    DocumentLockedError,
    LivingDocumentService,
    NotLivingDocumentError,
    _document_settings,
)

from .document_upload_service import DocumentNotFoundError, _uploader_display
from .editing_rights import require_editable_collection

# Largest image accepted for a pending spot. Generous for a screenshot or a photo, small enough that
# nobody parks a video in the object store through this door.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


class DraftNotFoundError(Exception):
    """The document has no draft (never had one, or it was validated, refused or lapsed)."""


class DraftExistsError(Exception):
    """A document has at most one draft: validate or refuse it before starting another edit."""


class DraftBusyError(Exception):
    """A worker job is still running on this draft."""


class DraftNotReadyError(Exception):
    """The draft isn't in a state this action works on (still running, or failed)."""


class NothingToValidateError(Exception):
    """The agent changed nothing: there is no draft file to promote."""


class UnknownImageError(Exception):
    """The draft has no pending image spot with that id."""


class UnsupportedImageError(Exception):
    """Not a PNG, JPEG or GIF, or too large."""


class ImagesNeedOdtError(Exception):
    """Images can only go into an ODT - a Markdown file doesn't carry them."""


class NoUploadedImageError(Exception):
    """Inserting was requested but nothing was uploaded (or everything is already in)."""


class DocumentDraftService:
    """The life of a draft (#169): the user asks for an edit, a worker produces it, the user
    validates, adjusts or refuses. The draft holds the document's edit lock throughout, so a
    validation can't collide with another write; if the user walks away the lock lapses and the
    draft with it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.documents = DocumentRepository(db)
        self.revisions = DocumentRevisionRepository(db)
        self.drafts = DocumentDraftRepository(db)
        self.tasks = TaskRepository(db)

    # -- user-facing -------------------------------------------------------------------------

    async def create(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, prompt: str
    ) -> DraftOut:
        document = await self._get_living_document(collection_id, user, document_id)
        await self._drop_if_lapsed(document)
        if await self.drafts.get_by_document(document.id) is not None:
            raise DraftExistsError(str(document_id))

        current = (await self.revisions.list_by_document(document.id))[0]
        now = datetime.now(UTC)
        token = uuid.uuid4().hex
        acquired = await self.documents.try_acquire_lock(
            document.id,
            user_id=user.user_id,
            display=_uploader_display(user),
            token=token,
            now=now,
            expires_at=now + self._ttl(),
        )
        if not acquired:
            await self.db.commit()
            await self.db.refresh(document)
            lock = DocumentLockOut.from_document(document, user.user_id, now)
            # (No live lock means it lapsed between the two statements: just ask again.)
            raise DocumentLockedError(lock) if lock else DraftBusyError(str(document_id))

        task_id = str(uuid.uuid4())
        draft = await self.drafts.create(
            document.id,
            base_revision=current.number,
            format_=current.format,
            prompt=prompt,
            user_id=user.user_id,
            user_display=_uploader_display(user),
            celery_task_id=task_id,
            lock_token=token,
        )
        await self._record_task(task_id, EDIT_DOCUMENT_TASK, user, document)
        await self.db.commit()
        payload = {
            "source_storage_key": document.storage_key,
            "prompt": prompt,
            "document_id": str(document.id),
            "base_revision": current.number,
            "format": current.format,
            "user_id": user.user_id,
            "previous_draft_key": None,
        }
        await self._enqueue(draft, document, lambda: enqueue_edit_document(payload, task_id=task_id))
        return await self._out(draft, document)

    async def get_current(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> DraftOut:
        """The draft and its state. Reading it renews the lock, so a client polling a running job
        (or keeping the preview open) keeps the draft alive; one that stopped lets it lapse."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        await self._touch(document, draft)
        return await self._out(draft, document)

    async def preview(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> tuple[bytes, str]:
        """(content, media type): the PDF of an edited ODT, the text of an edited Markdown -
        streamed through the backend, never a storage URL."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        await self._touch(document, draft)
        out = DraftOut.from_model(draft, None)
        if out.preview == "pdf":
            return storage.get_object(draft.preview_pdf_key)[0], "application/pdf"
        if out.preview == "markdown":
            return storage.get_object(draft.draft_storage_key)[0], FORMAT_MEDIA_TYPES["md"]
        raise DraftNotReadyError("no preview")

    async def adjust(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, prompt: str
    ) -> DraftOut:
        """A new instruction applied on top of the current draft (or from the document itself when
        the draft failed or changed nothing). The previous files are removed once the new job
        reports."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        if draft.status == DraftStatus.PENDING:
            raise DraftBusyError(str(draft.id))
        await self._touch(document, draft)

        current = (await self.revisions.list_by_document(document.id))[0]
        task_id = str(uuid.uuid4())
        previous = draft.draft_storage_key if draft.edited else None
        draft.status = DraftStatus.PENDING
        draft.job_kind = "edit"
        draft.prompt = prompt
        draft.error = None
        draft.celery_task_id = task_id
        await self._record_task(task_id, EDIT_DOCUMENT_TASK, user, document)
        await self.db.commit()
        payload = {
            "source_storage_key": document.storage_key,
            "prompt": prompt,
            "document_id": str(document.id),
            "base_revision": current.number,
            "format": current.format,
            "user_id": user.user_id,
            "previous_draft_key": previous,
        }
        await self._enqueue(draft, document, lambda: enqueue_edit_document(payload, task_id=task_id))
        return await self._out(draft, document)

    async def upload_image(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        image_id: str,
        content: bytes,
        content_type: str,
    ) -> DraftOut:
        """Stores the file the user gives for one pending image spot. Nothing runs yet: several
        images can be uploaded, then inserted together (insert_images) in a single new preview."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        if draft.format != "odt":
            raise ImagesNeedOdtError(draft.format)
        if draft.status != DraftStatus.READY:
            raise DraftNotReadyError(draft.status)
        image = self._pending_image(draft, image_id)
        if image.get("inserted") or not any(content.startswith(s) for s in _IMAGE_SIGNATURES):
            raise UnsupportedImageError(image_id)
        if len(content) > MAX_IMAGE_BYTES:
            raise UnsupportedImageError(image_id)
        await self._touch(document, draft)

        key = f"drafts/{document.id}/images/{image_id}-{uuid.uuid4().hex}"
        old_key = image.get("storage_key")
        storage.put_object(key, content, content_type=content_type or "application/octet-stream")
        # A new list with a new dict for this image: a JSONB column only notices a reassignment, not
        # an edit made in place to the list it already holds.
        draft.pending_images = [
            {**i, "storage_key": key, "content_type": content_type} if i["id"] == image_id else dict(i)
            for i in draft.pending_images
        ]
        await self.db.commit()
        if old_key:
            storage.delete_objects([old_key])
        return await self._out(draft, document)

    async def insert_images(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> DraftOut:
        """Starts the job that puts every uploaded-but-not-inserted image into the draft and renders
        a new preview."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        if draft.format != "odt":
            raise ImagesNeedOdtError(draft.format)
        if draft.status != DraftStatus.READY:
            raise DraftNotReadyError(draft.status)
        uploaded = [i for i in draft.pending_images if i.get("storage_key") and not i.get("inserted")]
        if not uploaded or not draft.draft_storage_key:
            raise NoUploadedImageError(str(draft.id))
        await self._touch(document, draft)

        task_id = str(uuid.uuid4())
        draft.status = DraftStatus.PENDING
        draft.job_kind = "images"
        draft.error = None
        draft.celery_task_id = task_id
        await self._record_task(task_id, INSERT_IMAGES_TASK, user, document)
        await self.db.commit()
        payload = {
            "draft_storage_key": draft.draft_storage_key,
            "document_id": str(document.id),
            "user_id": user.user_id,
            "images": [
                {
                    "id": i["id"],
                    "description": i["description"],
                    "storage_key": i["storage_key"],
                    "section": i.get("section"),
                    "after_paragraph": i.get("after_paragraph"),
                }
                for i in uploaded
            ],
        }
        await self._enqueue(draft, document, lambda: enqueue_insert_images(payload, task_id=task_id))
        return await self._out(draft, document)

    async def validate(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> DocumentOut:
        """Promotes the draft to the document's next revision (origin: chat) and reindexes the
        document - the only way a draft ever becomes part of the collection. The draft's lock and
        base revision make it fail cleanly if the document moved on."""
        document, draft = await self._live_draft(collection_id, user, document_id)
        if draft.status != DraftStatus.READY:
            raise DraftNotReadyError(draft.status)
        if not draft.edited or not draft.draft_storage_key:
            raise NothingToValidateError(str(draft.id))

        current = (await self.revisions.list_by_document(document.id))[0]
        content, _ = storage.get_object(draft.draft_storage_key)
        result = await LivingDocumentService(self.db).replace(
            collection_id,
            user,
            document_id,
            current.filename,
            content,
            FORMAT_MEDIA_TYPES[draft.format],
            base_revision=draft.base_revision,
            lock_token=draft.lock_token,
            origin=RevisionOrigin.CHAT,
        )
        await self._drop(draft, release_lock=False)  # replace() already released it
        return result

    async def refuse(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> None:
        document, draft = await self._live_draft(collection_id, user, document_id)
        await self._drop(draft, document=document)

    # -- reported by the worker (internal) ---------------------------------------------------

    async def record_result(self, celery_task_id: str, result: DraftResultIn) -> None:
        draft = await self.drafts.get_by_celery_id(celery_task_id)
        if draft is None:
            # The draft was refused or lapsed while the job ran: its files are orphans.
            storage.delete_objects([k for k in (result.draft_storage_key, result.preview_pdf_key) if k])
            return

        stale = [k for k in (draft.draft_storage_key, draft.preview_pdf_key) if k]
        stale = [k for k in stale if k not in (result.draft_storage_key, result.preview_pdf_key)]
        draft.draft_storage_key = result.draft_storage_key
        draft.preview_pdf_key = result.preview_pdf_key
        draft.status = DraftStatus.READY
        draft.error = None
        if result.kind == "edit":
            draft.edited = result.edited
            draft.operations_summary = result.operations_summary
            old_images = [i.get("storage_key") for i in draft.pending_images if i.get("storage_key")]
            stale += old_images
            draft.pending_images = [
                {**image.model_dump(), "storage_key": None, "content_type": None, "inserted": False}
                for image in result.pending_images
            ]
        else:
            stale += self._mark_inserted(draft)
            lines = [line for line in (draft.operations_summary, result.operations_summary) if line]
            draft.operations_summary = "\n".join(lines)
        await self.db.commit()
        storage.delete_objects(stale)

    async def record_failure(self, celery_task_id: str, error: str) -> None:
        draft = await self.drafts.get_by_celery_id(celery_task_id)
        if draft is None:
            return
        # A failed image insertion leaves the draft as it was, still ready, with the reason shown;
        # a failed edit leaves nothing to look at.
        draft.status = DraftStatus.READY if draft.job_kind == "images" else DraftStatus.FAILED
        draft.error = error
        await self.db.commit()

    # -- helpers -----------------------------------------------------------------------------

    def _ttl(self) -> timedelta:
        return timedelta(seconds=_document_settings.DOCUMENT_LOCK_TTL_SECONDS)

    async def _get_living_document(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> Document:
        await require_editable_collection(self.collections, user, collection_id)
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if document.kind != "living":
            raise NotLivingDocumentError(str(document_id))
        return document

    async def _live_draft(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> tuple[Document, DocumentDraft]:
        document = await self._get_living_document(collection_id, user, document_id)
        await self._drop_if_lapsed(document)
        draft = await self.drafts.get_by_document(document.id)
        if draft is None:
            raise DraftNotFoundError(str(document_id))
        return document, draft

    @staticmethod
    def _holds_lock(document: Document, draft: DocumentDraft, now: datetime) -> bool:
        return (
            document.lock_token == draft.lock_token
            and document.lock_expires_at is not None
            and document.lock_expires_at > now
        )

    async def _drop_if_lapsed(self, document: Document) -> None:
        """An abandoned draft is cleaned up lazily, the next time anyone looks at the document:
        its lock expired (or was broken), so nothing protects it any more."""
        draft = await self.drafts.get_by_document(document.id)
        if draft is not None and not self._holds_lock(document, draft, datetime.now(UTC)):
            await self._drop(draft, release_lock=False)

    async def _touch(self, document: Document, draft: DocumentDraft) -> None:
        now = datetime.now(UTC)
        renewed = await self.documents.renew_lock(
            document.id, token=draft.lock_token, now=now, expires_at=now + self._ttl()
        )
        await self.db.commit()
        if not renewed:
            await self._drop(draft, release_lock=False)
            raise DraftNotFoundError(str(document.id))
        await self.db.refresh(document)

    async def _drop(self, draft: DocumentDraft, *, release_lock: bool = True, document: Document | None = None) -> None:
        keys = self.drafts.storage_keys(draft)
        if release_lock:
            document = document or await self.documents.get(draft.document_id)
            if document is not None:
                # The lock columns are written with bulk UPDATEs: the object in memory may be stale.
                await self.db.refresh(document)
            if document is not None and document.lock_token == draft.lock_token:
                await self.documents.clear_lock(document)
        await self.drafts.delete(draft)
        await self.db.commit()
        storage.delete_objects(keys)

    async def _enqueue(self, draft: DocumentDraft, document: Document, send: Any) -> None:
        """Sends the job; if the broker refuses, the draft and its lock would be stuck waiting for a
        job that never runs - undo them and let the error surface."""
        try:
            send()
        except Exception:
            await self._drop(draft, document=document)
            raise

    async def _record_task(self, task_id: str, name: str, user: RequestContext, document: Document) -> None:
        await self.tasks.create(
            task_id, name, user.user_id, document_id=document.id, collection_id=document.collection_id
        )

    async def _out(self, draft: DocumentDraft, document: Document) -> DraftOut:
        await self.db.refresh(draft)
        await self.db.refresh(document)
        return DraftOut.from_model(draft, document.lock_expires_at)

    @staticmethod
    def _pending_image(draft: DocumentDraft, image_id: str) -> dict[str, Any]:
        for image in draft.pending_images:
            if image["id"] == image_id:
                return image
        raise UnknownImageError(image_id)

    def _mark_inserted(self, draft: DocumentDraft) -> list[str]:
        """The uploaded images are in the draft file now: flag them, and return their uploaded
        copies, which are no longer needed."""
        images = [dict(image) for image in draft.pending_images]
        done = []
        for image in images:
            if image.get("storage_key") and not image.get("inserted"):
                done.append(image["storage_key"])
                image["inserted"] = True
                image["storage_key"] = None
        draft.pending_images = images
        return done
