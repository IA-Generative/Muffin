import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import any_, func, literal, not_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.collection import Collection, CollectionVisibility


class Ancestor(NamedTuple):
    id: uuid.UUID
    name: str
    visibility: CollectionVisibility


class CollectionHierarchyRepository:
    """Tree traversal over Collection.parent_id (#213) - kept apart from CollectionRepository,
    which stays about a single collection and the permission barrier around it. Nothing here
    filters by access: callers decide what the caller may see (owner check, sharing, ...)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def descendant_ids(self, collection_id: uuid.UUID) -> list[uuid.UUID]:
        """Every collection below this one, at any depth, never including itself.

        UNION (not UNION ALL) is the cycle guard: a row already produced is never produced
        again, so the recursion terminates even if inconsistent data ever formed a loop that
        CollectionHierarchyService.set_parent would have refused."""
        descendants = (
            select(Collection.id).where(Collection.parent_id == collection_id).cte("descendants", recursive=True)
        )
        descendants = descendants.union(select(Collection.id).where(Collection.parent_id == descendants.c.id))
        result = await self.db.scalars(select(descendants.c.id).where(descendants.c.id != collection_id))
        return list(result.all())

    async def subtree_ids(self, collection_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
        """These collections and every collection below them, deduplicated - overlapping
        subtrees (a parent and its own child both given) count once. Same UNION cycle guard as
        descendant_ids."""
        if not collection_ids:
            return []
        subtree = select(Collection.id).where(Collection.id.in_(collection_ids)).cte("subtree", recursive=True)
        subtree = subtree.union(select(Collection.id).where(Collection.parent_id == subtree.c.id))
        result = await self.db.scalars(select(subtree.c.id))
        return list(result.all())

    async def children_with_description(self, parent_id: uuid.UUID) -> list[tuple[str, str]]:
        """(name, description) of the direct children that have a description yet, by name -
        what a parent's description is rolled up from (#218)."""
        result = await self.db.execute(
            select(Collection.name, Collection.description)
            .where(Collection.parent_id == parent_id, Collection.description != "")
            .order_by(Collection.name)
        )
        return [(name, description) for name, description in result.all()]

    async def names(self, collection_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Ancestor]:
        """Each collection as an Ancestor-shaped row, to prepend to its own ancestor_chains entry
        when a path must include the collection itself."""
        if not collection_ids:
            return {}
        result = await self.db.execute(
            select(Collection.id, Collection.name, Collection.visibility).where(Collection.id.in_(collection_ids))
        )
        return {row.id: Ancestor(row.id, row.name, row.visibility) for row in result.all()}

    async def ancestor_chains(self, collection_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[Ancestor]]:
        """Every ancestor of each collection, nearest (its parent) first - one
        query for a whole page of collections rather than one per collection. Roots have no
        entry.

        Each row carries the ids already walked (`visited`) and stops before revisiting one:
        UNION alone can't guard this walk, rows differ by depth so a loop would never repeat
        the exact same row."""
        if not collection_ids:
            return {}
        ancestors = (
            select(
                Collection.id.label("start_id"),
                Collection.parent_id.label("ancestor_id"),
                literal(1).label("depth"),
                array([Collection.id, Collection.parent_id]).label("visited"),
            )
            .where(Collection.id.in_(collection_ids), Collection.parent_id.is_not(None))
            .cte("ancestors", recursive=True)
        )
        step = aliased(Collection)
        ancestors = ancestors.union_all(
            select(
                ancestors.c.start_id,
                step.parent_id,
                ancestors.c.depth + 1,
                func.array_append(ancestors.c.visited, step.parent_id),
            ).where(
                step.id == ancestors.c.ancestor_id,
                step.parent_id.is_not(None),
                not_(step.parent_id == any_(ancestors.c.visited)),
            )
        )
        result = await self.db.execute(
            select(ancestors.c.start_id, Collection.id, Collection.name, Collection.visibility)
            .join(Collection, Collection.id == ancestors.c.ancestor_id)
            .order_by(ancestors.c.start_id, ancestors.c.depth)
        )
        chains: dict[uuid.UUID, list[Ancestor]] = defaultdict(list)
        for start_id, ancestor_id, name, visibility in result.all():
            chains[start_id].append(Ancestor(ancestor_id, name, visibility))
        return dict(chains)

    async def child_ids_by_parent(self, parent_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
        """Direct children of each given collection. Parents without children have no entry."""
        if not parent_ids:
            return {}
        result = await self.db.execute(
            select(Collection.parent_id, Collection.id).where(Collection.parent_id.in_(parent_ids))
        )
        children: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for parent_id, child_id in result.all():
            children[parent_id].append(child_id)
        return dict(children)
