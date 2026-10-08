import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DocumentSettings
from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import PROCESS_DOCUMENT_TASK, enqueue_process_document
from app.models.document import Document, DocumentKind
from app.models.document_revision import DocumentRevision, RevisionOrigin
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.document_revision_repository import DocumentRevisionRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.document import DocumentLockGrantOut, DocumentLockOut, DocumentOut, DocumentRevisionOut
from app.services import vector_store

from .document_upload_service import DocumentNotFoundError, _uploader_display
from .editing_rights import require_editable_collection

# Extension -> format. ODT is the reference format; Markdown is the lighter one (#174).
SUPPORTED_FORMATS = {".odt": "odt", ".md": "md"}
# Served back on download - the format never changes across a document's revisions.
FORMAT_MEDIA_TYPES = {"odt": "application/vnd.oasis.opendocument.text", "md": "text/markdown; charset=utf-8"}


class UnsupportedFormatError(Exception):
    """The file isn't an ODT or a Markdown file."""


class FormatMismatchError(Exception):
    """A replacement must keep the document's format - an ODT stays an ODT."""


class NotLivingDocumentError(Exception):
    """Revisions only exist on a living document."""


class RevisionNotFoundError(Exception):
    pass


class DocumentLockedError(Exception):
    """Someone else holds a live edit lock (or the caller didn't present the right token)."""

    def __init__(self, lock: DocumentLockOut) -> None:
        super().__init__("document is locked")
        self.lock = lock


class LockLostError(Exception):
    """The caller's lock expired or was released since they acquired it."""


class RevisionConflictError(Exception):
    """The document moved on since the revision the caller based their change on."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f"current revision is {current_revision}")
        self.current_revision = current_revision


# Exposed as a module attribute so tests can swap it out with monkeypatch.setattr, same as
# app/core/sharing.py's settings.
_document_settings = DocumentSettings()


def _detect_format(filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    try:
        return SUPPORTED_FORMATS[extension]
    except KeyError as error:
        raise UnsupportedFormatError(filename) from error


class LivingDocumentService:
    """Living documents (#166): files whose content evolves through append-only revisions.
    Replacing one swaps the file Document.storage_key points at and reprocesses that single
    document - nothing else in the collection is touched, unlike reindex_collection."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.documents = DocumentRepository(db)
        self.revisions = DocumentRevisionRepository(db)
        self.tasks = TaskRepository(db)

    async def create(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        filename: str,
        content: bytes,
        content_type: str,
        *,
        origin: RevisionOrigin = RevisionOrigin.UPLOAD,
    ) -> DocumentOut:
        await self._get_editable_collection(collection_id, user)
        safe_name = os.path.basename(filename) or "document"
        format_ = _detect_format(safe_name)
        storage_key = self._put_file(collection_id, safe_name, content, content_type)

        document = await self.documents.create_file(
            collection_id, safe_name, storage_key, user.user_id, _uploader_display(user), kind=DocumentKind.LIVING
        )
        await self.revisions.create(
            document.id,
            storage_key=storage_key,
            filename=safe_name,
            format_=format_,
            origin=origin,
            created_by_user_id=user.user_id,
            created_by_display=_uploader_display(user),
        )
        await self.db.commit()
        await self._enqueue_processing(document, user)
        return DocumentOut.model_validate(document)

    async def create_markdown(
        self, collection_id: uuid.UUID, user: RequestContext, name: str, content: str
    ) -> DocumentOut:
        """A Markdown living document written from scratch in the UI, rather than uploaded: the
        same Document + revision 1 as an upload, just with origin=ui."""
        base = os.path.basename(name.strip()) or "document"
        filename = base if base.lower().endswith(".md") else f"{base}.md"
        return await self.create(
            collection_id,
            user,
            filename,
            content.encode("utf-8"),
            FORMAT_MEDIA_TYPES["md"],
            origin=RevisionOrigin.UI,
        )

    async def download(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, number: int | None
    ) -> tuple[bytes, str, str]:
        """(content, filename, media type) of a revision - the current one by default. Streamed
        through the backend like page screenshots, never a direct storage URL."""
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        revision = (
            await self._current_revision(document)
            if number is None
            else await self.revisions.get_by_number(document.id, number)
        )
        if revision is None:
            raise RevisionNotFoundError(str(number))
        content, _ = storage.get_object(revision.storage_key)
        return content, revision.filename, FORMAT_MEDIA_TYPES[revision.format]

    async def replace(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str,
        *,
        base_revision: int,
        lock_token: str | None = None,
        origin: RevisionOrigin = RevisionOrigin.UPLOAD,
    ) -> DocumentOut:
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        safe_name = os.path.basename(filename) or "document"
        format_ = _detect_format(safe_name)
        current = await self._current_revision(document)
        if format_ != current.format:
            raise FormatMismatchError(f"{current.format} -> {format_}")
        # Both guards run before the file is uploaded, so a refused write leaves no orphan object.
        self._assert_can_write(document, user, lock_token, base_revision, current.number)

        storage_key = self._put_file(collection_id, safe_name, content, content_type)
        await self._append_revision(
            document,
            current.number,
            storage_key=storage_key,
            filename=safe_name,
            format_=format_,
            origin=origin,
            user=user,
            orphan_key=storage_key,
        )
        await self._reprocess(document, collection_id, storage_key, user)
        return DocumentOut.model_validate(document)

    async def list_revisions(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> list[DocumentRevisionOut]:
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        revisions = await self.revisions.list_by_document(document.id)
        # Newest first, so the current revision is the head of the list.
        return [
            DocumentRevisionOut.model_validate(revision).model_copy(update={"is_current": index == 0})
            for index, revision in enumerate(revisions)
        ]

    async def restore(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        number: int,
        *,
        base_revision: int,
        lock_token: str | None = None,
    ) -> DocumentOut:
        """Makes an older revision current again by appending a new revision that points at the
        same file - history is never rewritten."""
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        source = await self.revisions.get_by_number(document.id, number)
        if source is None:
            raise RevisionNotFoundError(str(number))
        current = await self._current_revision(document)
        self._assert_can_write(document, user, lock_token, base_revision, current.number)

        await self._append_revision(
            document,
            current.number,
            storage_key=source.storage_key,
            filename=source.filename,
            format_=source.format,
            origin=RevisionOrigin.RESTORE,
            user=user,
            restored_from_number=source.number,
        )
        await self._reprocess(document, collection_id, source.storage_key, user)
        return DocumentOut.model_validate(document)

    async def acquire_lock(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> DocumentLockGrantOut:
        """Takes the soft edit lock (#170) for a limited time. The returned token is the only
        way to write while it's held - it's what tells "my own session" from "someone else's",
        since the same user can be in two tabs (or, later, behind a chat edit job)."""
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        now = datetime.now(UTC)
        token = uuid.uuid4().hex
        expires_at = now + self._ttl()
        acquired = await self.documents.try_acquire_lock(
            document.id,
            user_id=user.user_id,
            display=_uploader_display(user),
            token=token,
            now=now,
            expires_at=expires_at,
        )
        await self.db.commit()
        await self.db.refresh(document)
        if not acquired:
            raise DocumentLockedError(self._current_lock(document, user, now))
        return DocumentLockGrantOut(
            locked_by_display=document.locked_by_display, expires_at=expires_at, held_by_me=True, token=token
        )

    async def renew_lock(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, token: str
    ) -> DocumentLockOut:
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        now = datetime.now(UTC)
        renewed = await self.documents.renew_lock(document.id, token=token, now=now, expires_at=now + self._ttl())
        await self.db.commit()
        if not renewed:
            raise LockLostError(str(document_id))
        await self.db.refresh(document)
        return self._current_lock(document, user, now)

    async def release_lock(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        token: str | None,
        *,
        force: bool = False,
    ) -> None:
        """Idempotent: releasing a document nobody holds is a no-op. Without the holder's token
        only force=true works - the collection owner (the only caller here) breaking a lock
        left by an abandoned session instead of waiting for its expiry."""
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        now = datetime.now(UTC)
        lock = DocumentLockOut.from_document(document, user.user_id, now)
        if lock is None:
            return
        if not force and token != document.lock_token:
            raise DocumentLockedError(lock)
        await self.documents.clear_lock(document)
        await self.db.commit()

    async def get_lock(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> DocumentLockOut | None:
        await self._get_editable_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        return DocumentLockOut.from_document(document, user.user_id, datetime.now(UTC))

    def _ttl(self) -> timedelta:
        return timedelta(seconds=_document_settings.DOCUMENT_LOCK_TTL_SECONDS)

    @staticmethod
    def _current_lock(document: Document, user: RequestContext, now: datetime) -> DocumentLockOut:
        lock = DocumentLockOut.from_document(document, user.user_id, now)
        if lock is None:  # Expired between the failed acquisition and this read - vanishingly rare.
            raise LockLostError(str(document.id))
        return lock

    @staticmethod
    def _assert_can_write(
        document: Document, user: RequestContext, lock_token: str | None, base_revision: int, current_revision: int
    ) -> None:
        """A write needs (1) not to collide with someone else's live lock - the holder's token
        is the only pass - and (2) to be based on the current revision, which also covers a lock
        that expired in the meantime and let another write land first."""
        lock = DocumentLockOut.from_document(document, user.user_id, datetime.now(UTC))
        if lock is not None and lock_token != document.lock_token:
            raise DocumentLockedError(lock)
        if base_revision != current_revision:
            raise RevisionConflictError(current_revision)

    async def _append_revision(
        self,
        document: Document,
        current_number: int,
        *,
        storage_key: str,
        filename: str,
        format_: str,
        origin: RevisionOrigin,
        user: RequestContext,
        restored_from_number: int | None = None,
        orphan_key: str | None = None,
    ) -> None:
        """Adds the revision, turning a lost race on the unique (document_id, number) constraint
        - two writers that both passed the guards without a lock - into the same conflict the
        base_revision check reports, instead of an opaque 500."""
        try:
            await self.revisions.create(
                document.id,
                storage_key=storage_key,
                filename=filename,
                format_=format_,
                origin=origin,
                created_by_user_id=user.user_id,
                created_by_display=_uploader_display(user),
                restored_from_number=restored_from_number,
            )
        except IntegrityError as error:
            await self.db.rollback()
            if orphan_key is not None:
                storage.delete_objects([orphan_key])
            raise RevisionConflictError((await self.revisions.current_number(document.id)) or current_number) from error

    async def _reprocess(
        self, document: Document, collection_id: uuid.UUID, storage_key: str, user: RequestContext
    ) -> None:
        """Single-document counterpart of reindex_collection: drops this document's embeddings
        and pages/chunks, points it at the new file and re-queues processing. Embeddings go
        first - once the chunk rows are cleared their ids can't be looked up anymore."""
        chunk_ids = await self.documents.list_chunk_ids(document.id)
        vector_store.delete_document_embeddings(collection_id, document.id, chunk_ids)
        orphaned_screenshot_keys = await self.documents.clear_content(document.id)
        await self.documents.set_current_file(document, storage_key)
        # The write ends the editing session it was done under.
        await self.documents.clear_lock(document)
        await self.db.commit()
        storage.delete_objects(orphaned_screenshot_keys)
        await self._enqueue_processing(document, user)

    async def _enqueue_processing(self, document: Document, user: RequestContext) -> None:
        celery_task_id = enqueue_process_document(str(document.id))
        await self.tasks.create(
            celery_task_id,
            PROCESS_DOCUMENT_TASK,
            user.user_id,
            document_id=document.id,
            collection_id=document.collection_id,
        )
        await self.db.commit()

    @staticmethod
    def _put_file(collection_id: uuid.UUID, safe_name: str, content: bytes, content_type: str) -> str:
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{safe_name}"
        storage.put_object(storage_key, content, content_type=content_type)
        return storage_key

    async def _current_revision(self, document: Document) -> DocumentRevision:
        revisions = await self.revisions.list_by_document(document.id)
        return revisions[0]

    async def _get_editable_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        await require_editable_collection(self.collections, user, collection_id)

    async def _get_living_document(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if document.kind != DocumentKind.LIVING:
            raise NotLivingDocumentError(str(document_id))
        return document
