import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection


class CollectionHierarchyRepository:
    """Tree traversal over Collection.parent_id (#213) - kept apart from CollectionRepository,
    which stays about a single collection and the permission barrier around it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def descendant_ids(self, collection_id: uuid.UUID) -> list[uuid.UUID]:
        """Every collection below this one, at any depth, never including itself. No access
        filtering - callers decide what the caller may see (owner check, sharing, ...).

        UNION (not UNION ALL) is the cycle guard: a row already produced is never produced
        again, so the recursion terminates even if inconsistent data ever formed a loop that
        CollectionHierarchyService.set_parent would have refused."""
        descendants = (
            select(Collection.id).where(Collection.parent_id == collection_id).cte("descendants", recursive=True)
        )
        descendants = descendants.union(select(Collection.id).where(Collection.parent_id == descendants.c.id))
        result = await self.db.scalars(select(descendants.c.id).where(descendants.c.id != collection_id))
        return list(result.all())
