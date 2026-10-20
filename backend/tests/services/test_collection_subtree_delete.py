import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.collection import Collection
from app.models.document import Document, DocumentType
from app.services.collection_service import CollectionService

OWNER_ID = "user-a"


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


def _owner() -> RequestContext:
    return RequestContext(user_id=OWNER_ID, email=f"{OWNER_ID}@example.com", roles=[], is_admin=False)


async def _create(name: str, parent_id=None) -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id=OWNER_ID, name=name, parent_id=parent_id)
        session.add(collection)
        await session.commit()
        return collection.id


async def _add_file(collection_id: uuid.UUID, storage_key: str) -> None:
    async with async_session_factory() as session:
        session.add(
            Document(collection_id=collection_id, name=storage_key, type=DocumentType.FILE, storage_key=storage_key)
        )
        await session.commit()


async def test_deleting_a_collection_cleans_up_its_whole_subtree(cleanup):
    root = await _create("Root")
    child = await _create("Child", parent_id=root)
    grandchild = await _create("Grandchild", parent_id=child)
    unrelated = await _create("Unrelated")
    await _add_file(root, "documents/root.pdf")
    await _add_file(grandchild, "documents/grandchild.pdf")
    await _add_file(unrelated, "documents/unrelated.pdf")

    with (
        patch("app.services.collection_service.storage.delete_objects") as delete_objects,
        patch("app.services.collection_service.vector_store.delete_collection") as delete_index,
    ):
        async with async_session_factory() as session:
            await CollectionService(session).delete_collection(root, _owner())

    assert sorted(delete_objects.call_args.args[0]) == ["documents/grandchild.pdf", "documents/root.pdf"]
    assert {call.args[0] for call in delete_index.call_args_list} == {root, child, grandchild}

    async with async_session_factory() as session:
        assert await session.get(Collection, child) is None
        assert await session.get(Collection, grandchild) is None
        assert await session.get(Collection, unrelated) is not None


async def test_deleting_a_child_leaves_its_parent_untouched(cleanup):
    root = await _create("Root")
    child = await _create("Child", parent_id=root)

    with (
        patch("app.services.collection_service.storage.delete_objects"),
        patch("app.services.collection_service.vector_store.delete_collection") as delete_index,
    ):
        async with async_session_factory() as session:
            await CollectionService(session).delete_collection(child, _owner())

    assert [call.args[0] for call in delete_index.call_args_list] == [child]
    async with async_session_factory() as session:
        assert await session.get(Collection, root) is not None
