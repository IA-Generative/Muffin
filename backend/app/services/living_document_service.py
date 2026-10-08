import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import PROCESS_DOCUMENT_TASK, enqueue_process_document
from app.models.document import Document, DocumentKind
from app.models.document_revision import DocumentRevision, RevisionOrigin
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.document_revision_repository import DocumentRevisionRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.document import DocumentOut, DocumentRevisionOut
from app.services import vector_store

from .collection_service import CollectionNotFoundError
from .document_upload_service import DocumentNotFoundError, _uploader_display

# Extension -> format. ODT is the reference format; Markdown is the lighter one (#174).
SUPPORTED_FORMATS = {".odt": "odt", ".md": "md"}


class UnsupportedFormatError(Exception):
    """The file isn't an ODT or a Markdown file."""


class FormatMismatchError(Exception):
    """A replacement must keep the document's format - an ODT stays an ODT."""


class NotLivingDocumentError(Exception):
    """Revisions only exist on a living document."""


class RevisionNotFoundError(Exception):
    pass


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
    ) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
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
            origin=RevisionOrigin.UPLOAD,
            created_by_user_id=user.user_id,
            created_by_display=_uploader_display(user),
        )
        await self.db.commit()
        await self._enqueue_processing(document, user)
        return DocumentOut.model_validate(document)

    async def replace(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        safe_name = os.path.basename(filename) or "document"
        format_ = _detect_format(safe_name)
        current = await self._current_revision(document)
        if format_ != current.format:
            raise FormatMismatchError(f"{current.format} -> {format_}")

        storage_key = self._put_file(collection_id, safe_name, content, content_type)
        await self.revisions.create(
            document.id,
            storage_key=storage_key,
            filename=safe_name,
            format_=format_,
            origin=RevisionOrigin.UPLOAD,
            created_by_user_id=user.user_id,
            created_by_display=_uploader_display(user),
        )
        await self._reprocess(document, collection_id, storage_key, user)
        return DocumentOut.model_validate(document)

    async def list_revisions(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> list[DocumentRevisionOut]:
        await self._get_owned_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        revisions = await self.revisions.list_by_document(document.id)
        # Newest first, so the current revision is the head of the list.
        return [
            DocumentRevisionOut.model_validate(revision).model_copy(update={"is_current": index == 0})
            for index, revision in enumerate(revisions)
        ]

    async def restore(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID, number: int
    ) -> DocumentOut:
        """Makes an older revision current again by appending a new revision that points at the
        same file - history is never rewritten."""
        await self._get_owned_collection(collection_id, user)
        document = await self._get_living_document(collection_id, document_id)
        source = await self.revisions.get_by_number(document.id, number)
        if source is None:
            raise RevisionNotFoundError(str(number))

        await self.revisions.create(
            document.id,
            storage_key=source.storage_key,
            filename=source.filename,
            format_=source.format,
            origin=RevisionOrigin.RESTORE,
            created_by_user_id=user.user_id,
            created_by_display=_uploader_display(user),
            restored_from_number=source.number,
        )
        await self._reprocess(document, collection_id, source.storage_key, user)
        return DocumentOut.model_validate(document)

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

    async def _get_owned_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        if await self.collections.get(collection_id, user.user_id) is None:
            raise CollectionNotFoundError(str(collection_id))

    async def _get_living_document(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if document.kind != DocumentKind.LIVING:
            raise NotLivingDocumentError(str(document_id))
        return document
