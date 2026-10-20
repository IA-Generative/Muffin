import uuid

import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.collection import Collection
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.services.collection_hierarchy_service import (
    CollectionHierarchyService,
    HierarchyCycleError,
    HierarchyOwnerMismatchError,
    TemporaryCollectionHierarchyError,
)

OWNER_ID = "user-a"


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _create(name: str, *, parent_id=None, owner_id: str = OWNER_ID, is_temporary: bool = False) -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner_id, name=name, parent_id=parent_id, is_temporary=is_temporary)
        session.add(collection)
        await session.commit()
        return collection.id


async def _set_parent(collection_id: uuid.UUID, parent_id: uuid.UUID | None) -> None:
    async with async_session_factory() as session:
        collection = await session.get(Collection, collection_id)
        parent = await session.get(Collection, parent_id) if parent_id else None
        await CollectionHierarchyService(session).set_parent(collection, parent)
        await session.commit()


async def _parent_of(collection_id: uuid.UUID) -> uuid.UUID | None:
    async with async_session_factory() as session:
        return (await session.get(Collection, collection_id)).parent_id


class TestDescendantIds:
    async def test_leaf_has_no_descendants(self, cleanup):
        leaf = await _create("Leaf")

        async with async_session_factory() as session:
            assert await CollectionHierarchyRepository(session).descendant_ids(leaf) == []

    async def test_returns_every_level_but_not_itself_nor_siblings(self, cleanup):
        root = await _create("Root")
        child = await _create("Child", parent_id=root)
        other_child = await _create("Other child", parent_id=root)
        grandchild = await _create("Grandchild", parent_id=child)
        great_grandchild = await _create("Great-grandchild", parent_id=grandchild)
        await _create("Unrelated root")

        async with async_session_factory() as session:
            repository = CollectionHierarchyRepository(session)
            assert set(await repository.descendant_ids(root)) == {child, other_child, grandchild, great_grandchild}
            assert set(await repository.descendant_ids(child)) == {grandchild, great_grandchild}

    async def test_terminates_on_inconsistent_cyclic_data(self, cleanup):
        """set_parent refuses cycles, but the traversal must not loop forever if one ever got
        written around it."""
        a = await _create("A")
        b = await _create("B", parent_id=a)
        async with async_session_factory() as session:
            (await session.get(Collection, a)).parent_id = b
            await session.commit()

        async with async_session_factory() as session:
            assert await CollectionHierarchyRepository(session).descendant_ids(a) == [b]


class TestSetParent:
    async def test_attaches_under_a_parent(self, cleanup):
        parent = await _create("Parent")
        child = await _create("Child")

        await _set_parent(child, parent)

        assert await _parent_of(child) == parent

    async def test_none_moves_back_to_the_root(self, cleanup):
        parent = await _create("Parent")
        child = await _create("Child", parent_id=parent)

        await _set_parent(child, None)

        assert await _parent_of(child) is None

    async def test_moves_a_subtree_under_another_branch(self, cleanup):
        root = await _create("Root")
        branch_a = await _create("A", parent_id=root)
        branch_b = await _create("B", parent_id=root)
        under_a = await _create("Under A", parent_id=branch_a)

        await _set_parent(branch_a, branch_b)

        assert await _parent_of(branch_a) == branch_b
        assert await _parent_of(under_a) == branch_a

    async def test_refuses_itself_as_parent(self, cleanup):
        collection = await _create("Self")

        with pytest.raises(HierarchyCycleError):
            await _set_parent(collection, collection)

    async def test_refuses_a_direct_child_as_parent(self, cleanup):
        parent = await _create("Parent")
        child = await _create("Child", parent_id=parent)

        with pytest.raises(HierarchyCycleError):
            await _set_parent(parent, child)
        assert await _parent_of(parent) is None

    async def test_refuses_a_deep_descendant_as_parent(self, cleanup):
        root = await _create("Root")
        child = await _create("Child", parent_id=root)
        grandchild = await _create("Grandchild", parent_id=child)

        with pytest.raises(HierarchyCycleError):
            await _set_parent(root, grandchild)

    async def test_refuses_a_parent_owned_by_someone_else(self, cleanup):
        parent = await _create("Theirs", owner_id="user-b")
        child = await _create("Mine")

        with pytest.raises(HierarchyOwnerMismatchError):
            await _set_parent(child, parent)

    async def test_refuses_a_temporary_child(self, cleanup):
        parent = await _create("Parent")
        temporary = await _create("Temp", is_temporary=True)

        with pytest.raises(TemporaryCollectionHierarchyError):
            await _set_parent(temporary, parent)

    async def test_refuses_a_temporary_parent(self, cleanup):
        temporary = await _create("Temp", is_temporary=True)
        child = await _create("Child")

        with pytest.raises(TemporaryCollectionHierarchyError):
            await _set_parent(child, temporary)
