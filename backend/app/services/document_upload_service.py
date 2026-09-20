import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import PROCESS_DOCUMENT_TASK, enqueue_process_document
from app.models.document import Document, DocumentStatus
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.collection import EntityOut, RelationOut
from app.schemas.document import (
    DocumentDetailOut,
    DocumentOut,
    DocumentPageOut,
    TabularProfileOut,
)
from app.schemas.pagination import Page, PaginationParams
from app.services import vector_store

from .collection_service import CollectionNotFoundError


class DocumentNotFoundError(Exception):
    pass


class DocumentUploadService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.documents = DocumentRepository(db)
        self.entities = EntityRepository(db)
        self.tasks = TaskRepository(db)

    async def list_documents(self, collection_id: uuid.UUID, user: RequestContext) -> list[DocumentOut]:
        await self._get_owned_collection(collection_id, user)
        documents = await self.documents.list_by_collection(collection_id)
        return [DocumentOut.model_validate(document) for document in documents]

    async def create_file_document(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
        safe_name = os.path.basename(filename) or "document"
        storage_key = f"documents/{collection_id}/{uuid.uuid4()}-{safe_name}"
        storage.put_object(storage_key, content, content_type=content_type)

        document = await self.documents.create_file(collection_id, safe_name, storage_key)
        await self.db.commit()
        celery_task_id = enqueue_process_document(str(document.id))
        await self.tasks.create(
            celery_task_id,
            PROCESS_DOCUMENT_TASK,
            user.user_id,
            document_id=document.id,
            collection_id=collection_id,
        )
        await self.db.commit()
        return DocumentOut.model_validate(document)

    async def create_url_document(self, collection_id: uuid.UUID, user: RequestContext, url: str) -> DocumentOut:
        await self._get_owned_collection(collection_id, user)
        document = await self.documents.create_url(collection_id, url)
        await self.db.commit()
        celery_task_id = enqueue_process_document(str(document.id))
        await self.tasks.create(
            celery_task_id,
            PROCESS_DOCUMENT_TASK,
            user.user_id,
            document_id=document.id,
            collection_id=collection_id,
        )
        await self.db.commit()
        return DocumentOut.model_validate(document)

    async def reindex_collection(self, collection_id: uuid.UUID, user: RequestContext) -> list[DocumentOut]:
        await self._get_owned_collection(collection_id, user)
        documents = await self.documents.list_by_collection(collection_id)

        orphaned_screenshot_keys: list[str] = []
        for document in documents:
            # Same reasoning as delete_document: clear_content wipes the Postgres chunks/pages,
            # so their Meilisearch embeddings must be deleted first or they'd survive as stale
            # vectors pointing at chunk ids that no longer exist.
            chunk_ids = await self.documents.list_chunk_ids(document.id)
            vector_store.delete_document_embeddings(collection_id, document.id, chunk_ids)
            orphaned_screenshot_keys.extend(await self.documents.clear_content(document.id))
            await self.documents.update_status(document, DocumentStatus.PENDING, progress=0, summary=None)
        await self.db.commit()
        storage.delete_objects(orphaned_screenshot_keys)

        for document in documents:
            celery_task_id = enqueue_process_document(str(document.id))
            await self.tasks.create(
                celery_task_id,
                PROCESS_DOCUMENT_TASK,
                user.user_id,
                document_id=document.id,
                collection_id=collection_id,
            )
        await self.db.commit()
        return [DocumentOut.model_validate(document) for document in documents]

    async def get_document(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> DocumentDetailOut:
        await self._get_owned_collection(collection_id, user)
        document = await self.documents.get_in_collection_with_tags(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        page_count = await self.documents.count_pages(document_id)
        return DocumentDetailOut(
            id=document.id,
            name=document.name,
            type=document.type,
            status=document.status,
            progress=document.progress,
            summary=document.summary,
            error=document.error,
            tags=[tag.tag for tag in document.tags],
            page_count=page_count,
        )

    async def get_tabular_profile(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> TabularProfileOut | None:
        await self._get_owned_collection(collection_id, user)
        await self._get_owned_document(collection_id, document_id)
        profile = await self.documents.get_tabular_profile(document_id)
        if profile is None:
            return None
        return TabularProfileOut.model_validate(profile)

    async def list_pages(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        pagination: PaginationParams,
    ) -> Page[DocumentPageOut]:
        await self._get_owned_collection(collection_id, user)
        await self._get_owned_document(collection_id, document_id)
        pages, total = await self.documents.list_pages_page(
            document_id, limit=pagination.limit, offset=pagination.offset
        )
        items = [
            DocumentPageOut(
                page_number=page.page_number,
                content=page.content,
                # A path on this same backend, not a presigned RustFS URL (§ never a public
                # storage link the browser talks to directly) - every fetch of it re-runs the
                # normal auth/ownership check below, instead of a link that keeps working on its
                # own, for whoever has it, until it expires.
                screenshot_url=(
                    f"/api/collections/{collection_id}/documents/{document_id}/pages/{page.page_number}/screenshot"
                    if page.screenshot
                    else None
                ),
            )
            for page in pages
        ]
        return pagination.to_page(items, total)

    async def get_page_screenshot(
        self,
        collection_id: uuid.UUID,
        user: RequestContext,
        document_id: uuid.UUID,
        page_number: int,
    ) -> tuple[bytes, str]:
        await self._get_owned_collection(collection_id, user)
        await self._get_owned_document(collection_id, document_id)
        page = await self.documents.get_page(document_id, page_number)
        if page is None or page.screenshot is None:
            raise DocumentNotFoundError(f"page {page_number} of document {document_id}")
        return storage.get_object(page.screenshot)

    async def list_entities(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> list[EntityOut]:
        await self._get_owned_collection(collection_id, user)
        await self._get_owned_document(collection_id, document_id)
        entities = await self.entities.list_by_document(document_id)
        return [
            EntityOut(
                id=entity.id,
                name=entity.name,
                type=entity.type,
                mentions=entity.mentions,
            )
            for entity in entities
        ]

    async def list_relations(
        self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> list[RelationOut]:
        await self._get_owned_collection(collection_id, user)
        await self._get_owned_document(collection_id, document_id)
        relations = await self.entities.list_relations_by_document(document_id)
        return [
            RelationOut(
                id=relation.id,
                from_entity=relation.from_entity.name,
                to=relation.to_entity.name,
                type=relation.type,
            )
            for relation in relations
        ]

    async def delete_document(self, collection_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID) -> None:
        await self._get_owned_collection(collection_id, user)
        document = await self._get_owned_document(collection_id, document_id)
        rustfs_keys = await self.documents.list_rustfs_keys_for_document(document_id)
        chunk_ids = await self.documents.list_chunk_ids(document_id)
        # Delete the Meilisearch embeddings *before* the Postgres rows go away - otherwise the
        # chunk ids can't be looked up anymore, and stale vectors would keep surfacing in search
        # results pointing at a document_id that no longer exists (FK violation at citation
        # materialization time, see SourceRepository.link_citations).
        vector_store.delete_document_embeddings(collection_id, document_id, chunk_ids)
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
