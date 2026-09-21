import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.collection import Collection
from app.models.conversation import Conversation


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(Conversation))
        await session.commit()


async def test_regular_collection_defaults_to_not_temporary(cleanup):
    async with async_session_factory() as session:
        collection = Collection(owner_id="user-a", name="Regular collection")
        session.add(collection)
        await session.commit()
        await session.refresh(collection)

    assert collection.is_temporary is False
    assert collection.conversation_id is None


async def test_temporary_collection_links_to_its_conversation(cleanup):
    async with async_session_factory() as session:
        conversation = Conversation(user_id="user-a")
        session.add(conversation)
        await session.flush()

        collection = Collection(
            owner_id="user-a",
            name="Temporary collection",
            is_temporary=True,
            conversation_id=conversation.id,
        )
        session.add(collection)
        await session.commit()

        # Reload from a fresh session so the relationship is actually queried, not just
        # reflecting the object already held in memory from this same transaction.
        conversation_id = conversation.id

    async with async_session_factory() as session:
        reloaded = await session.get(Conversation, conversation_id)
        await session.refresh(reloaded, attribute_names=["temporary_collection"])
        assert reloaded.temporary_collection is not None
        assert reloaded.temporary_collection.is_temporary is True


async def test_conversation_id_is_unique_per_collection(cleanup):
    """At most one temporary collection per conversation (uq_collections_conversation_id)."""
    async with async_session_factory() as session:
        conversation = Conversation(user_id="user-a")
        session.add(conversation)
        await session.flush()

        session.add(Collection(owner_id="user-a", name="First", is_temporary=True, conversation_id=conversation.id))
        await session.commit()

    async with async_session_factory() as session:
        session.add(Collection(owner_id="user-a", name="Second", is_temporary=True, conversation_id=conversation.id))
        with pytest.raises(Exception, match="uq_collections_conversation_id"):
            await session.commit()


async def test_deleting_conversation_cascades_to_its_temporary_collection(cleanup):
    async with async_session_factory() as session:
        conversation = Conversation(user_id="user-a")
        session.add(conversation)
        await session.flush()
        collection = Collection(owner_id="user-a", name="Temp", is_temporary=True, conversation_id=conversation.id)
        session.add(collection)
        await session.commit()
        collection_id = collection.id
        conversation_id = conversation.id

    async with async_session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        await session.delete(conversation)
        await session.commit()

    async with async_session_factory() as session:
        assert await session.get(Collection, collection_id) is None
