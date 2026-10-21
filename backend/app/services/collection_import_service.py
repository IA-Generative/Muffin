import uuid
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.core.tasks import IMPORT_ZIP_TASK, enqueue_import_zip
from app.models.collection import Collection
from app.models.collection_import import CollectionImport, CollectionImportStatus
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_import_repository import CollectionImportRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.collection_import import AttachDecision, CollectionImportOut, CollectionImportResult
from app.services import vector_store
from app.services.collection_hierarchy_service import CollectionHierarchyService
from app.services.collection_service import CollectionService, ParentCollectionNotFoundError
from app.services.description_rollup_service import DescriptionRollupService
from app.services.document_upload_service import DocumentUploadService, _uploader_display
from app.services.embedding_model_lookup import default_embedding_model
from app.services.search_service import embed_text


class InvalidArchiveError(Exception):
    """Not a ZIP archive at all - refused before anything is stored or created."""


class CollectionImportNotFoundError(Exception):
    pass


class ConversationNotFoundError(Exception):
    pass


class InvalidAttachDecisionError(Exception):
    """An attach decision that can't apply: nothing suggested to accept, no target to choose, or
    an import with no attach suggestion at all."""


class ImportTargetError(Exception):
    """An internal call from the worker that doesn't belong to this import - a collection of
    another owner, or a storage key outside the target collection."""


def unique_name(name: str, taken: set[str]) -> str:
    """ "Archive", then "Archive (2)", "Archive (3)"... - two imports of the same ZIP at the same
    place never end up merged."""
    if name not in taken:
        return name
    suffix = 2
    while f"{name} ({suffix})" in taken:
        suffix += 1
    return f"{name} ({suffix})"


class CollectionImportService:
    """Turns an uploaded ZIP into a collection and its sub-collections (#223). The root collection
    is created synchronously, when the archive is uploaded; the archive itself is read by
    worker/document_process's import_zip, which creates everything below it through the internal
    routes here."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.imports = CollectionImportRepository(db)
        self.collections = CollectionRepository(db)
        self.conversations = ConversationRepository(db)
        self.tasks = TaskRepository(db)
        self.collection_service = CollectionService(db)
        self.hierarchy = CollectionHierarchyRepository(db)
        self.hierarchy_rules = CollectionHierarchyService(db)
        self.documents = DocumentUploadService(db)

    # How many candidates an attach suggestion keeps, as for a filing suggestion (§122).
    ATTACH_TOP_K = 3

    async def start(
        self,
        user: RequestContext,
        archive: BinaryIO,
        filename: str,
        size: int | None,
        *,
        parent_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> CollectionImportOut:
        """`parent_id`: dropped into a collection's Documents tab - the ZIP's collection goes
        right under it. `conversation_id`: dropped into a conversation - top level, pinned to that
        conversation's runs. Neither: the "Fichiers à ranger" page - top level."""
        # No size limit on the archive itself: it is streamed to the object store, never held in
        # memory, and what it expands to is bounded worker-side (ZIP_IMPORT_*: file count, sizes,
        # compression ratio), where a zip bomb would actually do harm.
        if not filename.lower().endswith(".zip") or not zipfile.is_zipfile(archive):
            raise InvalidArchiveError(filename)
        archive.seek(0)
        if conversation_id is not None and await self.conversations.get(conversation_id, user.user_id) is None:
            raise ConversationNotFoundError(str(conversation_id))

        name = PurePosixPath(filename.replace("\\", "/")).stem.strip() or "Archive"
        name = unique_name(name, await self.collections.sibling_names(user.user_id, parent_id))
        # Raises ParentCollectionNotFoundError/HierarchyError for a parent the user can't use.
        root = await self.collection_service.create_collection(user, name=name, parent_id=parent_id)

        collection_import = await self.imports.create(
            CollectionImport(
                owner_id=user.user_id,
                owner_display=_uploader_display(user),
                archive_name=filename,
                status=CollectionImportStatus.PENDING,
                root_collection_id=root.id,
                conversation_id=conversation_id,
                attach_eligible=parent_id is None,
            )
        )
        collection_import.archive_key = f"imports/{collection_import.id}.zip"
        storage.upload_fileobj(collection_import.archive_key, archive, content_type="application/zip")
        await self.db.commit()

        celery_task_id = enqueue_import_zip(str(collection_import.id))
        await self.tasks.create(celery_task_id, IMPORT_ZIP_TASK, user.user_id, collection_id=root.id)
        await self.db.commit()
        await self.db.refresh(collection_import, attribute_names=["created_at"])
        return await self._present(collection_import)

    async def get(self, import_id: uuid.UUID, user: RequestContext) -> CollectionImportOut:
        return await self._present(await self._get_owned(import_id, user))

    async def list(
        self, user: RequestContext, *, conversation_id: uuid.UUID | None = None, awaiting_attachment: bool = False
    ) -> list[CollectionImportOut]:
        imports = await self.imports.list_for_owner(
            user.user_id, conversation_id=conversation_id, awaiting_attachment=awaiting_attachment
        )
        return [await self._present(collection_import) for collection_import in imports]

    async def suggest_attachment(self, collection_id: uuid.UUID) -> None:
        """Recomputes the attach suggestion of the import this collection is the root of, if
        any, from its current description - called whenever a collection's description changes,
        a no-op for every other collection. Same ranking as a filing suggestion (§122): the
        description embedded with the global embedding model, compared to the descriptions of the
        collections the owner has - never the imported collection itself or anything below it."""
        collection_import = await self.imports.get_by_root_collection(collection_id)
        if collection_import is None or not collection_import.attach_eligible or collection_import.attach_dismissed:
            return
        root = await self.collections.get_by_id(collection_id)
        if root is None or root.parent_id is not None or not root.description:
            return

        model = await default_embedding_model(self.db)
        if model is None:
            return
        embedding = await embed_text(model, root.description)
        excluded = {root.id, *await self.hierarchy.descendant_ids(root.id)}
        candidate_ids = [cid for cid in await self.collections.list_owned_ids(root.owner_id) if cid not in excluded]
        results = vector_store.search_collections(root.description, embedding, candidate_ids, limit=self.ATTACH_TOP_K)
        collections_by_id = {c.id: c for c in await self.collections.get_by_ids([cid for cid, _ in results])}
        candidates = [
            {
                "collection_id": str(cid),
                "collection_name": collections_by_id[cid].name,
                "collection_description": collections_by_id[cid].description,
                "score": score,
            }
            for cid, score in results
            if cid in collections_by_id  # defensive: deleted between search and here
        ]
        collection_import.attach_candidates = candidates or None
        collection_import.suggested_parent_id = uuid.UUID(candidates[0]["collection_id"]) if candidates else None
        collection_import.suggested_parent_score = candidates[0]["score"] if candidates else None
        await self.db.commit()

    async def decide_attachment(
        self, import_id: uuid.UUID, user: RequestContext, decision: AttachDecision
    ) -> CollectionImportOut:
        """The user's answer to an attach suggestion: "accept" moves the imported collection
        under the suggested one, "choose_other" under `target_collection_id`, "dismiss" leaves it
        at the top level and stops suggesting. Moving follows the usual rules (#215) - only under
        a collection the user owns, never under the collection itself or below it."""
        collection_import = await self._get_owned(import_id, user)
        if not collection_import.attach_eligible or collection_import.root_collection_id is None:
            raise InvalidAttachDecisionError(decision.action)

        if decision.action == "dismiss":
            collection_import.attach_dismissed = True
            await self.db.commit()
            return await self._present(collection_import)

        target_id = (
            collection_import.suggested_parent_id if decision.action == "accept" else decision.target_collection_id
        )
        if target_id is None:
            raise InvalidAttachDecisionError(decision.action)
        target = await self.collections.get(target_id, user.user_id)
        if target is None:
            raise ParentCollectionNotFoundError(str(target_id))
        root = await self.collections.get(collection_import.root_collection_id, user.user_id)
        if root is None:
            raise InvalidAttachDecisionError(decision.action)
        # Raises HierarchyError on a cycle - before anything is committed.
        await self.hierarchy_rules.set_parent(root, target)
        if root.description:
            # Its new parent's rolled-up description now has it to draw from (#218).
            await DescriptionRollupService(self.db).schedule(target.id)
        await self.db.commit()
        return await self._present(collection_import)

    # --- Internal, called by the worker ---

    async def begin(self, import_id: uuid.UUID) -> CollectionImport:
        collection_import = await self._get_by_id(import_id)
        collection_import.status = CollectionImportStatus.RUNNING
        await self.db.commit()
        return collection_import

    async def create_sub_collection(self, import_id: uuid.UUID, parent_id: uuid.UUID, name: str) -> uuid.UUID:
        """A ZIP folder becoming a sub-collection - with a copy of its parent's settings, like any
        sub-collection (#215)."""
        collection_import = await self._get_by_id(import_id)
        parent = await self._get_target(collection_import, parent_id)
        collection = await self.collections.create(
            owner_id=collection_import.owner_id,
            name=name,
            embedding_model=parent.settings.embedding_model,
            settings_template=parent.settings,
        )
        await self.hierarchy_rules.set_parent(collection, parent)
        await self.db.commit()
        return collection.id

    async def add_document(
        self, import_id: uuid.UUID, collection_id: uuid.UUID, name: str, storage_key: str
    ) -> uuid.UUID:
        collection_import = await self._get_by_id(import_id)
        await self._get_target(collection_import, collection_id)
        if not storage_key.startswith(f"documents/{collection_id}/"):
            raise ImportTargetError(storage_key)
        document = await self.documents.register_stored_file(
            collection_id,
            name,
            storage_key,
            collection_import.owner_id,
            collection_import.owner_display,
            bulk=True,
        )
        return document.id

    async def finish(self, import_id: uuid.UUID, result: CollectionImportResult) -> None:
        collection_import = await self._get_by_id(import_id)
        collection_import.status = CollectionImportStatus(result.status)
        collection_import.summary = result.summary
        collection_import.error = result.error
        archive_key, collection_import.archive_key = collection_import.archive_key, None
        await self.db.commit()
        # Best-effort and after the commit, same as every other RustFS cleanup.
        if archive_key:
            storage.delete_objects([archive_key])

    async def _get_owned(self, import_id: uuid.UUID, user: RequestContext) -> CollectionImport:
        collection_import = await self.imports.get(import_id, user.user_id)
        if collection_import is None:
            raise CollectionImportNotFoundError(str(import_id))
        return collection_import

    async def _present(self, collection_import: CollectionImport) -> CollectionImportOut:
        root = (
            await self.collections.get_by_id(collection_import.root_collection_id)
            if collection_import.root_collection_id is not None
            else None
        )
        return CollectionImportOut.from_model(collection_import, root)

    async def _get_by_id(self, import_id: uuid.UUID) -> CollectionImport:
        collection_import = await self.imports.get_by_id(import_id)
        if collection_import is None:
            raise CollectionImportNotFoundError(str(import_id))
        return collection_import

    async def _get_target(self, collection_import: CollectionImport, collection_id: uuid.UUID) -> Collection:
        """A collection the worker may write into for this import: one of its owner's. Enough on
        its own - the worker only ever names collections it got back from this same import."""
        collection = await self.collections.get(collection_id, collection_import.owner_id)
        if collection is None:
            raise ImportTargetError(str(collection_id))
        return collection
