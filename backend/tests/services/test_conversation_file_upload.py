import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.task import Task
from app.repositories.collection_repository import CollectionRepository
from app.services.document_upload_service import DocumentUploadService

USER_ID = "user-a"


@pytest.fixture
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.execute(delete(Conversation))
        await session.commit()


def _user() -> RequestContext:
    return RequestContext(user_id=USER_ID, email=f"{USER_ID}@example.com", roles=[], is_admin=False)


async def _create_conversation() -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=USER_ID)
        session.add(conversation)
        await session.commit()
        return conversation.id


class TestGetOrCreateTemporaryForConversation:
    async def test_creates_a_private_temporary_collection_on_first_call(self, cleanup):
        conversation_id = await _create_conversation()

        async with async_session_factory() as session:
            repo = CollectionRepository(session)
            collection = await repo.get_or_create_temporary_for_conversation(
                conversation_id, USER_ID, embedding_model="text-embedding-3-small"
            )
            await session.commit()

        assert collection.is_temporary is True
        assert collection.visibility == CollectionVisibility.PRIVATE
        assert collection.conversation_id == conversation_id
        assert collection.owner_id == USER_ID
        assert collection.settings is not None
        assert collection.settings.embedding_model == "text-embedding-3-small"

    async def test_second_call_returns_the_same_collection(self, cleanup):
        conversation_id = await _create_conversation()

        async with async_session_factory() as session:
            repo = CollectionRepository(session)
            first = await repo.get_or_create_temporary_for_conversation(
                conversation_id, USER_ID, embedding_model="text-embedding-3-small"
            )
            await session.commit()
            first_id = first.id

        async with async_session_factory() as session:
            repo = CollectionRepository(session)
            second = await repo.get_or_create_temporary_for_conversation(
                conversation_id, USER_ID, embedding_model="text-embedding-3-small"
            )
            await session.commit()

        assert second.id == first_id

    async def test_get_temporary_for_conversation_is_none_before_any_upload(self, cleanup):
        conversation_id = await _create_conversation()

        async with async_session_factory() as session:
            repo = CollectionRepository(session)
            assert await repo.get_temporary_for_conversation(conversation_id) is None


class TestCreateConversationFileDocument:
    async def test_reuses_the_same_temporary_collection_across_uploads(self, cleanup):
        conversation_id = await _create_conversation()

        with (
            patch("app.services.document_upload_service.storage.put_object"),
            patch(
                "app.services.document_upload_service.enqueue_process_document",
                side_effect=["celery-task-id-1", "celery-task-id-2"],
            ),
        ):
            async with async_session_factory() as session:
                service = DocumentUploadService(session)
                first = await service.create_conversation_file_document(
                    conversation_id, _user(), "a.txt", b"hello", "text/plain"
                )
            async with async_session_factory() as session:
                service = DocumentUploadService(session)
                second = await service.create_conversation_file_document(
                    conversation_id, _user(), "b.txt", b"world", "text/plain"
                )

        assert first.name == "a.txt"
        assert second.name == "b.txt"

        async with async_session_factory() as session:
            repo = CollectionRepository(session)
            collection = await repo.get_temporary_for_conversation(conversation_id)
            documents = await repo.count_documents([collection.id])
            assert documents[collection.id] == 2
