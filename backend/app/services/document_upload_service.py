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
    FilingCandidateOut,
    TabularProfileOut,
)
from app.schemas.pagination import Page, PaginationParams
from app.services import embedding_model_lookup, vector_store

from .collection_service import FALLBACK_EMBEDDING_MODEL, CollectionNotFoundError


class DocumentNotFoundError(Exception):
    pass


class InvalidFilingDecisionError(Exception):
    pass


def _uploader_display(user: RequestContext) -> str:
    """ "Jean D." style (first name + last-name initial), rather than a hash (no recognition
    value) or the full name (unnecessarily exposed everywhere it's shown) - see §122. Falls back
    to the email's local part, then the raw user id, for an identity provider that doesn't
    populate first_name/last_name."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name[0]}."
    if user.first_name:
        return user.first_name
    if user.email:
        return user.email.split("@")[0]
    return user.user_id


def _document_out(document: Document) -> DocumentOut:
    out = DocumentOut.model_validate(document)
    if document.suggested_collection is not None:
        out.suggested_collection_name = document.suggested_collection.name
    return out


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
        return [_document_out(document) for document in documents]

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

        document = await self.documents.create_file(
            collection_id, safe_name, storage_key, user.user_id, _uploader_display(user)
        )
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

    async def create_conversation_file_document(
        self,
        conversation_id: uuid.UUID,
        user: RequestContext,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentOut:
        """Upload a file straight into a conversation (§ conv-files) rather than a permanent
        collection the user manages explicitly. Gets or lazily creates the conversation's
        temporary collection, then hands off to create_file_document unchanged - no separate
        storage/indexing path, a conversation file is an ordinary Document like any other."""
        embedding_model = await embedding_model_lookup.default_embedding_model(self.db) or FALLBACK_EMBEDDING_MODEL
        collection = await self.collections.get_or_create_temporary_for_conversation(
            conversation_id, user.user_id, embedding_model=embedding_model
        )
        return await self.create_file_document(collection.id, user, filename, content, content_type)

    async def upload_standalone_for_filing(
        self,
        user: RequestContext,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> DocumentOut:
        """Upload a file straight to the "Fichiers à ranger" review page (§122 follow-up) - no
        conversation at all, unlike create_conversation_file_document. Gets or lazily creates
        this user's own standalone holding collection, then hands off to create_file_document
        unchanged, same reasoning as the conversation path."""
        embedding_model = await embedding_model_lookup.default_embedding_model(self.db) or FALLBACK_EMBEDDING_MODEL
        collection = await self.collections.get_or_create_personal_holding(
            user.user_id, embedding_model=embedding_model
        )
        return await self.create_file_document(collection.id, user, filename, content, content_type)

    async def list_conversation_documents(self, conversation_id: uuid.UUID, user: RequestContext) -> list[DocumentOut]:
        """Files attached to a conversation, via its temporary collection. Empty list (never a
        404) if nothing has been uploaded yet - the temporary collection simply doesn't exist."""
        collection = await self.collections.get_temporary_for_conversation(conversation_id)
        if collection is None:
            return []
        return await self.list_documents(collection.id, user)

    async def delete_conversation_document(
        self, conversation_id: uuid.UUID, user: RequestContext, document_id: uuid.UUID
    ) -> None:
        """Deletes a file from a conversation's temporary collection - reuses delete_document
        unchanged (RustFS + DB + Meilisearch cleanup). No temporary collection at all means this
        document can't possibly be in it, same as DocumentNotFoundError for a real collection."""
        collection = await self.collections.get_temporary_for_conversation(conversation_id)
        if collection is None:
            raise DocumentNotFoundError(str(document_id))
        await self.delete_document(collection.id, user, document_id)

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

    async def list_files_to_file(self, user: RequestContext) -> list[FilingCandidateOut]:
        """The "Fichiers à ranger" review page (§122): every file this user uploaded that isn't
        sitting in a permanent collection they still control - either still in its conversation's
        temporary collection, or in a collection whose ownership changed since (see
        DocumentRepository.list_to_file)."""
        documents = await self.documents.list_to_file(user.user_id)
        return [
            FilingCandidateOut(
                id=document.id,
                name=document.name,
                added_by_display=document.added_by_display,
                collection_id=document.collection.id,
                collection_name=document.collection.name,
                collection_is_temporary=document.collection.is_temporary,
                collection_editable=document.collection.owner_id == user.user_id,
                suggested_collection_id=document.suggested_collection_id,
                suggested_collection_name=(
                    document.suggested_collection.name if document.suggested_collection else None
                ),
                suggested_collection_score=document.suggested_collection_score,
                filing_candidates=document.filing_candidates,
                filing_dismissed=document.filing_dismissed,
                created_at=document.created_at,
            )
            for document in documents
        ]

    async def decide_filing(
        self,
        document_id: uuid.UUID,
        user: RequestContext,
        *,
        action: str,
        target_collection_id: uuid.UUID | None,
    ) -> DocumentOut:
        """The user's answer to a filing suggestion (§122) - "accept" files into
        suggested_collection_id, "choose_other" into target_collection_id (must be one they
        own), "dismiss" leaves the file exactly where it is, just silences the chat notification.
        Authorization is "did I upload this file" (added_by_user_id), not "do I own its current
        collection" - the whole point is surfacing files that ended up somewhere the uploader no
        longer controls, and dismissing/refiling one of those must still work."""
        document = await self.documents.get_with_suggestion(document_id)
        if document is None or document.added_by_user_id != user.user_id:
            raise DocumentNotFoundError(str(document_id))

        if action == "dismiss":
            await self.documents.set_filing_dismissed(document)
            await self.db.commit()
            return _document_out(document)

        if action == "accept":
            resolved_target = document.suggested_collection_id
        elif action == "choose_other":
            resolved_target = target_collection_id
        else:
            raise InvalidFilingDecisionError(action)
        if resolved_target is None:
            raise InvalidFilingDecisionError(action)

        await self._get_owned_collection(resolved_target, user)
        await self._move_document_to_collection(document, resolved_target, user)
        return _document_out(document)

    async def _move_document_to_collection(
        self, document: Document, target_collection_id: uuid.UUID, user: RequestContext
    ) -> None:
        """Re-homes a document in place (stable id, see DocumentRepository.move_to_collection)
        and fully reprocesses it under the target collection's own chunking/embedding settings -
        never a raw vector copy, since the source and target collections aren't guaranteed to
        share the same embedding_model. Same building blocks as reindex_collection."""
        old_collection_id = document.collection_id
        chunk_ids = await self.documents.list_chunk_ids(document.id)
        vector_store.delete_document_embeddings(old_collection_id, document.id, chunk_ids)
        orphaned_screenshot_keys = await self.documents.clear_content(document.id)
        await self.documents.move_to_collection(document, target_collection_id)
        await self.db.commit()
        storage.delete_objects(orphaned_screenshot_keys)

        celery_task_id = enqueue_process_document(str(document.id))
        await self.tasks.create(
            celery_task_id,
            PROCESS_DOCUMENT_TASK,
            user.user_id,
            document_id=document.id,
            collection_id=target_collection_id,
        )
        await self.db.commit()

    async def _get_owned_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        collection = await self.collections.get(collection_id, user.user_id)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))

    async def _get_owned_document(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get_in_collection(collection_id, document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        return document
