"""The bucket is shared with Open WebUI (#453): a file copied from it is read under the key it has there, and Muffin
never deletes it - it is still theirs. What Muffin made from it (page screenshots, ...) goes away with the document."""

import uuid

import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.collection import Collection
from app.models.document import Document, DocumentPage, DocumentType
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _collection_with_two_files(session) -> tuple[Collection, Document, Document]:
    collection = Collection(owner_id="u", name="shared", source="owui", external_id="kb1")
    session.add(collection)
    await session.flush()
    copied = Document(
        collection_id=collection.id,
        name="copied.pdf",
        type=DocumentType.FILE,
        source="owui",
        external_id="kb1/f1",
        storage_key="f1_copied.pdf",
    )
    own = Document(
        collection_id=collection.id, name="own.pdf", type=DocumentType.FILE, storage_key=f"documents/{uuid.uuid4()}.pdf"
    )
    session.add_all([copied, own])
    await session.flush()
    session.add(DocumentPage(document_id=copied.id, page_number=1, content="x", screenshot="screenshots/copied-1.png"))
    await session.flush()
    return collection, copied, own


async def test_deleting_a_collection_leaves_the_files_copied_from_the_other_system(monkeypatch):
    async with async_session_factory() as session:
        collection, copied, own = await _collection_with_two_files(session)
        await session.commit()

        keys = await CollectionRepository(session).list_rustfs_keys([collection.id])

    assert "f1_copied.pdf" not in keys
    assert own.storage_key in keys
    assert "screenshots/copied-1.png" in keys


async def test_deleting_a_document_copied_from_the_other_system_leaves_its_file():
    async with async_session_factory() as session:
        _, copied, own = await _collection_with_two_files(session)
        await session.commit()

        copied_keys = await DocumentRepository(session).list_rustfs_keys_for_document(copied.id)
        own_keys = await DocumentRepository(session).list_rustfs_keys_for_document(own.id)

    assert "f1_copied.pdf" not in copied_keys and "screenshots/copied-1.png" in copied_keys
    assert own.storage_key in own_keys
