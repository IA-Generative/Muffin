from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository


class HierarchyError(Exception):
    """Base for every rule a parent/child link must satisfy (#213) - lets a router map them all
    to one 4xx while each subclass still says which rule was broken."""


class HierarchyCycleError(HierarchyError):
    """The new parent is the collection itself or one of its descendants."""


class HierarchyOwnerMismatchError(HierarchyError):
    """A child always has its parent's owner - checked here rather than inferred, so a caller
    that already holds both collections can never silently link two owners' trees."""


class TemporaryCollectionHierarchyError(HierarchyError):
    """Temporary collections (conversation files, personal holding) are never part of a tree,
    neither as child nor as parent."""


class CollectionHierarchyService:
    """The rules of the sub-collection tree the database can't express on its own (see the
    check constraints on Collection for the ones it can). Never commits - the caller owns the
    transaction, same as the repositories."""

    def __init__(self, db: AsyncSession) -> None:
        self.hierarchy = CollectionHierarchyRepository(db)

    async def set_parent(self, collection: Collection, parent: Collection | None) -> None:
        """Attaches `collection` under `parent`, or moves it back to the root with None. The
        caller is expected to have already checked the user may write to both."""
        if parent is None:
            collection.parent_id = None
            return

        if collection.is_temporary or parent.is_temporary:
            raise TemporaryCollectionHierarchyError(str(collection.id))
        if parent.owner_id != collection.owner_id:
            raise HierarchyOwnerMismatchError(str(collection.id))
        if parent.id == collection.id or parent.id in await self.hierarchy.descendant_ids(collection.id):
            raise HierarchyCycleError(str(collection.id))

        collection.parent_id = parent.id
