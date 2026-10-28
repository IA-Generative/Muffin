import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.models.collection import Collection
from app.models.document import Document, DocumentType
from app.models.document_revision import DocumentRevision, RevisionOrigin
from app.models.evaluation import EvaluationRun
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


async def _add_file(collection_id: uuid.UUID, storage_key: str) -> uuid.UUID:
    async with async_session_factory() as session:
        document = Document(
            collection_id=collection_id, name=storage_key, type=DocumentType.FILE, storage_key=storage_key
        )
        session.add(document)
        await session.commit()
        return document.id


async def _add_revision(document_id: uuid.UUID, storage_key: str) -> None:
    async with async_session_factory() as session:
        session.add(
            DocumentRevision(
                document_id=document_id,
                number=1,
                storage_key=storage_key,
                filename="living.md",
                format="md",
                origin=RevisionOrigin.UPLOAD,
            )
        )
        await session.commit()


async def _add_evaluation_run(collection_id: uuid.UUID, results_key: str, report_key: str) -> None:
    async with async_session_factory() as session:
        session.add(
            EvaluationRun(
                collection_id=collection_id,
                pair_count=1,
                llm_model="judge",
                results_json_key=results_key,
                report_html_key=report_key,
            )
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


async def test_deleting_a_collection_cleans_up_revisions_and_evaluation_artifacts(cleanup):
    collection = await _create("Collection")
    document_id = await _add_file(collection, "documents/living.md")
    await _add_revision(document_id, "documents/living-v1.md")
    await _add_evaluation_run(collection, "evaluations/results.json", "evaluations/report.html")

    with (
        patch("app.services.collection_service.storage.delete_objects") as delete_objects,
        patch("app.services.collection_service.vector_store.delete_collection"),
    ):
        async with async_session_factory() as session:
            await CollectionService(session).delete_collection(collection, _owner())

    assert sorted(delete_objects.call_args.args[0]) == [
        "documents/living-v1.md",
        "documents/living.md",
        "evaluations/report.html",
        "evaluations/results.json",
    ]


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
