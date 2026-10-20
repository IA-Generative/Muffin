import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.collection import Collection
from app.models.document import Document, DocumentType

OWNER_ID = "user-a"


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _create(name: str, parent_id=None) -> Collection:
    async with async_session_factory() as session:
        collection = Collection(owner_id=OWNER_ID, name=name, parent_id=parent_id)
        session.add(collection)
        await session.commit()
        return collection


async def test_root_collection_has_no_parent(cleanup):
    collection = await _create("Root")

    assert collection.parent_id is None


async def test_child_links_to_its_parent(cleanup):
    parent = await _create("Parent")
    child = await _create("Child", parent_id=parent.id)

    async with async_session_factory() as session:
        reloaded = await session.get(Collection, child.id)
        assert reloaded.parent_id == parent.id


async def test_collection_cannot_be_its_own_parent(cleanup):
    collection = await _create("Self")

    async with async_session_factory() as session:
        reloaded = await session.get(Collection, collection.id)
        reloaded.parent_id = reloaded.id
        with pytest.raises(Exception, match="ck_collections_not_own_parent"):
            await session.commit()


async def test_temporary_collection_cannot_have_a_parent(cleanup):
    parent = await _create("Parent")

    async with async_session_factory() as session:
        session.add(Collection(owner_id=OWNER_ID, name="Temp", is_temporary=True, parent_id=parent.id))
        with pytest.raises(Exception, match="ck_collections_temporary_has_no_parent"):
            await session.commit()


async def test_deleting_a_parent_cascades_to_the_whole_subtree(cleanup):
    parent = await _create("Parent")
    child = await _create("Child", parent_id=parent.id)
    grandchild = await _create("Grandchild", parent_id=child.id)
    sibling_root = await _create("Unrelated root")

    async with async_session_factory() as session:
        document = Document(collection_id=grandchild.id, name="deep.pdf", type=DocumentType.FILE)
        session.add(document)
        await session.commit()
        document_id = document.id

    async with async_session_factory() as session:
        await session.delete(await session.get(Collection, parent.id))
        await session.commit()

    async with async_session_factory() as session:
        assert await session.get(Collection, child.id) is None
        assert await session.get(Collection, grandchild.id) is None
        assert await session.get(Document, document_id) is None
        assert await session.get(Collection, sibling_root.id) is not None
