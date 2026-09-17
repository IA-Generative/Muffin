import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import enqueue_process_document
from app.models.document import Document, DocumentStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentOut

from .collection_service import CollectionNotFoundError


class DocumentNotFoundError(Exception):
    pass


class DocumentUploadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.documents = DocumentRepository(db)

    async def list_documents(self, collection_id: uuid.UUID, user: RequestContext) -> list[DocumentOut]:
        await self._get_owned_collection(collection_id, user)
        documents = await self.documents.list_by_collection(collection_id)
        return [DocumentOut.model_validate(document) for document in documents]

    async def create_file_document(
        self, collection_id: uuid.UUID, user: RequestContext, filename: str, content: bytes, content_type: str
    ) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
        safe_name = os.path.basename(filename) or "document"
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{safe_name}"
        storage.put_object(storage_key, content, content_type=content_type)

        document = await self.documents.create_file(collection_id, safe_name, storage_key)
        await self.db.commit()
        enqueue_process_document(str(document.id))
        return DocumentOut.model_validate(document)

    async def create_url_document(self, collection_id: uuid.UUID, user: RequestContext, url: str) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
        document = await self.documents.create_url(collection_id, url)
        await self.db.commit()
        enqueue_process_document(str(document.id))
        return DocumentOut.model_validate(document)

    async def reindex_collection(self, collection_id: uuid.UUID, user: RequestContext) -> list[DocumentOut]:
        await self._get_owned_collection(collection_id, user)
        documents = await self.documents.list_by_collection(collection_id)

        orphaned_screenshot_keys: list[str] = []
        for document in documents:
            orphaned_screenshot_keys.extend(await self.documents.clear_content(document.id))
            await self.documents.update_status(document, DocumentStatus.PENDING, progress=0, summary=None)
        await self.db.commit()
        storage.delete_objects(orphaned_screenshot_keys)

        for document in documents:
            enqueue_process_document(str(document.id))
        return [DocumentOut.model_validate(document) for document in documents]

    async def delete_document(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> None:
        await self._get_owned_collection(collection_id, user)
        document = await self._get_owned_document(collection_id, document_id)
        rustfs_keys = await self.documents.list_rustfs_keys_for_document(document_id)
        await self.documents.delete(document)
        await self.db.commit()
        storage.delete_objects(rustfs_keys)

    async def _get_owned_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        collection = await self.collections.get(collection_id, user.user_id)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))

    async def _get_owned_document(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        return document
