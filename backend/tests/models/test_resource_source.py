import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import async_session_factory
from app.models.collection import Collection
from app.models.document import Document, DocumentType
from app.models.group import Group, GroupMember, ResourceSource


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(Group))
        await session.commit()


async def test_what_is_made_in_muffin_has_no_external_id(cleanup):
    async with async_session_factory() as session:
        collection = Collection(owner_id="user-a", name="Mine")
        group = Group(name="Team")
        session.add_all([collection, group])
        await session.commit()
        await session.refresh(collection)
        await session.refresh(group)

    assert (collection.source, collection.external_id) == (ResourceSource.MUFFIN, None)
    assert (group.source, group.external_id) == (ResourceSource.MUFFIN, None)


async def test_two_resources_of_muffin_can_both_have_no_external_id(cleanup):
    async with async_session_factory() as session:
        session.add_all([Collection(owner_id="u", name="a"), Collection(owner_id="u", name="b")])
        session.add_all([Group(name="a"), Group(name="b")])
        await session.commit()


@pytest.mark.parametrize("make", [lambda: Group(name="g"), lambda: Collection(owner_id="u", name="c")])
async def test_a_copy_of_the_same_resource_cannot_exist_twice(cleanup, make):
    async with async_session_factory() as session:
        for _ in range(2):
            resource = make()
            resource.source, resource.external_id = ResourceSource.OWUI, "owui-1"
            session.add(resource)
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_document_is_found_by_the_id_it_has_in_open_webui(cleanup):
    async with async_session_factory() as session:
        collection = Collection(owner_id="u", name="c")
        session.add(collection)
        await session.flush()
        session.add(
            Document(
                collection_id=collection.id,
                name="test.txt",
                type=DocumentType.FILE,
                source=ResourceSource.OWUI,
                external_id="file-1",
            )
        )
        await session.commit()
        found = await session.scalar(
            select(Document).where(Document.source == ResourceSource.OWUI, Document.external_id == "file-1")
        )
    assert found.name == "test.txt"


async def test_members_leave_with_their_group(cleanup):
    async with async_session_factory() as session:
        group = Group(name="Team")
        session.add(group)
        await session.flush()
        session.add_all(
            [GroupMember(group_id=group.id, user_id="sub-1"), GroupMember(group_id=group.id, user_id="sub-2")]
        )
        await session.commit()
        await session.delete(group)
        await session.commit()
        assert (await session.scalars(select(GroupMember))).all() == []
