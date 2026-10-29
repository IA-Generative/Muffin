"""The pipeline does not compute twice what it computed for the same file (#300)."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentPage, DocumentStatus, DocumentTag
from app.models.document_stage import DocumentStage, PipelineStage
from app.models.entity import Entity, Relation
from app.models.qa import QaOrigin, QaPair
from app.repositories.document_stage_repository import DocumentStageRepository
from app.repositories.entity_repository import EntityRepository
from app.services import vector_store
from app.services.document_upload_service import DocumentUploadService

API_KEY = "test-worker-key"
USER = RequestContext(user_id="dev-user", email="dev@example.com", roles=["user"], is_admin=False, groups=[])
FILE = "f" * 64
FP = {stage: f"{stage.value}-fingerprint" for stage in PipelineStage}
# What each stage of a fully processed source announced: one piece, or the windows of its pages.
PIECES = {PipelineStage.QA: ["window:1-2"], PipelineStage.ENTITIES: ["pages:1-2"]}


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


@pytest.fixture
def index(monkeypatch):
    """Qdrant, RustFS and the embeddings API replaced. `vectors` holds what the source collection's
    index has, by point id; the rest records what is written, copied and removed."""
    state = {
        "vectors": {},
        "points": [],
        "documents": [],
        "qa_points": [],
        "copied": [],
        "deleted_objects": [],
        "deleted_points": [],
        "embedded": [],
        "read_error": None,
    }

    def read_vectors(collection_id, point_ids):
        if state["read_error"]:
            raise state["read_error"]
        return {point_id: state["vectors"][point_id] for point_id in point_ids if point_id in state["vectors"]}

    async def embed_text(model, text):
        state["embedded"].append((model, text))
        return [9.0, 9.0]

    monkeypatch.setattr(vector_store, "read_vectors", read_vectors)
    monkeypatch.setattr(
        vector_store,
        "upsert_points",
        lambda collection_id, points, model, *, next_index, documents=None: (
            state["points"].append((collection_id, points, model)),
            state["documents"].append(documents),
        ),
    )
    monkeypatch.setattr(
        vector_store,
        "delete_points",
        lambda collection_id, ids, *, next_index: state["deleted_points"].extend(ids),
    )
    monkeypatch.setattr(
        vector_store,
        "upsert_qa_embedding",
        lambda collection_id, qa_id, embedding, text, model, document_id=None: state["qa_points"].append(
            (qa_id, embedding, model)
        ),
    )
    monkeypatch.setattr(vector_store, "delete_qa_embeddings", lambda *args: None)
    monkeypatch.setattr(vector_store, "delete_chunk_embeddings", lambda *args: None)
    monkeypatch.setattr(vector_store, "delete_document_embeddings", lambda *args: None)
    monkeypatch.setattr("app.core.storage.copy_object", lambda source, target: state["copied"].append((source, target)))
    monkeypatch.setattr("app.core.storage.delete_objects", lambda keys: state["deleted_objects"].extend(keys))
    monkeypatch.setattr("app.services.result_reuse.embed_text", embed_text)
    monkeypatch.setattr("app.services.index_vectors.embed_text", embed_text)
    return state


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _collection(model="model-a") -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model=model)
        session.add(collection)
        await session.commit()
        return collection.id


async def _document(collection_id, *, content_hash=FILE, summary=None) -> uuid.UUID:
    async with async_session_factory() as session:
        document = Document(
            collection_id=collection_id,
            name="report.pdf",
            type="file",
            storage_key="k",
            content_hash=content_hash,
            status=DocumentStatus.INDEXED,
            summary=summary,
        )
        session.add(document)
        await session.commit()
        return document.id


async def _processed_source(collection_id, index, *, complete=tuple(PipelineStage)) -> uuid.UUID:
    """A document of the file that went through the whole pipeline: its pages (the first with a
    screenshot), 3 chunks with vectors, a summary, QA pairs (generated, validated, manual), entities and
    relations of one window, tags."""
    source_id = await _document(collection_id, summary="The summary.")
    async with async_session_factory() as session:
        session.add_all(
            [
                DocumentPage(document_id=source_id, page_number=1, content="page one", screenshot="shots/one.png"),
                DocumentPage(document_id=source_id, page_number=2, content="page two"),
                DocumentTag(document_id=source_id, tag="legal"),
                DocumentTag(document_id=source_id, tag="contrat"),
            ]
        )
        chunks = [Chunk(document_id=source_id, index=i, text=f"chunk {i}", token_count=2) for i in range(3)]
        session.add_all(chunks)
        await session.flush()
        index["vectors"].update({chunk.id: ([float(chunk.index), 0.5], "model-a") for chunk in chunks})
        index["vectors"][source_id] = ([7.0, 7.0], "model-a")
        generated = [
            QaPair(
                collection_id=collection_id,
                document_id=source_id,
                question=question,
                answer="An answer.",
                origin=QaOrigin.GENERATED,
                validated=validated,
                generation_key="window:1-2",
                source_page=1,
                source_excerpt="passage",
                source_start=12,
                source_end=19,
            )
            for question, validated in (("Generated?", False), ("Validated?", True))
        ]
        manual = QaPair(
            collection_id=collection_id,
            document_id=source_id,
            question="Manual?",
            answer="Yes.",
            origin=QaOrigin.MANUAL,
            validated=True,
        )
        session.add_all([*generated, manual])
        await session.flush()
        index["vectors"][generated[0].id] = ([3.0, 3.0], "model-a")
        await EntityRepository(session).replace_window(
            collection_id,
            source_id,
            "pages:1-2",
            [("Acme Corp", "organisation", 2), ("Alice", "personne", 1)],
            [("Alice", "Acme Corp", "works_at")],
        )
        stages = DocumentStageRepository(session)
        for stage in complete:
            await stages.begin(source_id, stage.value, FP[stage], PIECES.get(stage, []))
            for piece in PIECES.get(stage, ["_"]):
                await stages.mark_done(source_id, stage.value, piece)
        await session.commit()
    return source_id


async def _begin(client, document_id, stage, *, fingerprint=None, expected=(), content_hash=None):
    body = {"fingerprint": fingerprint or FP[stage], "expected": list(expected)}
    if content_hash:
        body["content_hash"] = content_hash
    response = await client.post(
        f"/api/internal/documents/{document_id}/stages/{stage.value}/begin", headers=_headers(), json=body
    )
    assert response.status_code == 200, response.text
    return response.json()["reused"]


async def _rows(model, document_id, *, order=None):
    async with async_session_factory() as session:
        statement = select(model).where(model.document_id == document_id)
        return (await session.execute(statement.order_by(order) if order is not None else statement)).scalars().all()


async def _stage(document_id, stage) -> DocumentStage | None:
    async with async_session_factory() as session:
        return await session.get(DocumentStage, (document_id, stage.value))


# -- a stage nobody computed ----------------------------------------------------------------------


async def test_a_stage_nobody_completed_is_for_the_worker_to_compute(client, index):
    collection_id = await _collection()
    document_id = await _document(collection_id)

    assert await _begin(client, document_id, PipelineStage.EXTRACTION) is False

    stage = await _stage(document_id, PipelineStage.EXTRACTION)
    assert stage.fingerprint == FP[PipelineStage.EXTRACTION] and stage.completed_at is None


async def test_a_stage_the_worker_computed_becomes_reusable_once_it_says_it_is_done(client, index):
    collection_id = await _collection()
    first = await _document(collection_id)
    await _begin(client, first, PipelineStage.SUMMARY)
    other = await _document(await _collection())
    assert await _begin(client, other, PipelineStage.SUMMARY) is False

    done = await client.post(f"/api/internal/documents/{first}/stages/summary/done", headers=_headers(), json={})
    assert done.status_code == 200
    async with async_session_factory() as session:
        (await session.get(Document, first)).summary = "Computed."
        await session.commit()
    third = await _document(await _collection())

    assert await _begin(client, third, PipelineStage.SUMMARY) is True


async def test_a_stage_run_in_pieces_says_where_it_is_and_which_piece_completed_it(client, index):
    """The fan-in of the extraction of a long document: its ranges of pages finish at the same time, and
    exactly one of them is told that it completed the stage."""
    document_id = await _document(await _collection())
    pieces = ["pages:1-25", "pages:26-50", "pages:51-60"]
    await _begin(client, document_id, PipelineStage.EXTRACTION, expected=pieces)

    async def done(piece):
        response = await client.post(
            f"/api/internal/documents/{document_id}/stages/extraction/done", headers=_headers(), json={"key": piece}
        )
        assert response.status_code == 200
        return response.json()

    assert await done(pieces[1]) == {"done": 1, "expected": 3, "complete": False, "completed_now": False}
    # A piece done twice (its task ran again) counts once.
    assert await done(pieces[1]) == {"done": 1, "expected": 3, "complete": False, "completed_now": False}
    assert await done(pieces[0]) == {"done": 2, "expected": 3, "complete": False, "completed_now": False}
    assert await done(pieces[2]) == {"done": 3, "expected": 3, "complete": True, "completed_now": True}
    # Complete already: a piece run again is not the one that completed it.
    assert await done(pieces[2]) == {"done": 3, "expected": 3, "complete": True, "completed_now": False}


async def test_a_stage_nobody_began_has_no_pieces_to_say_where_it_is(client, index):
    document_id = await _document(await _collection())

    response = await client.post(
        f"/api/internal/documents/{document_id}/stages/extraction/done", headers=_headers(), json={"key": "pages:1-2"}
    )

    assert response.json() == {"done": 0, "expected": 0, "complete": False, "completed_now": False}


@pytest.mark.parametrize("case", ["another fingerprint", "another file", "source incomplete", "no hash"])
async def test_a_stage_is_only_reused_from_the_same_file_under_the_same_fingerprint(client, index, case):
    source_collection = await _collection()
    complete = tuple(PipelineStage) if case != "source incomplete" else ()
    await _processed_source(source_collection, index, complete=complete)
    target = await _document(
        await _collection(), content_hash=None if case == "no hash" else ("0" * 64 if case == "another file" else FILE)
    )
    fingerprint = "another-fingerprint" if case == "another fingerprint" else None

    assert await _begin(client, target, PipelineStage.EXTRACTION, fingerprint=fingerprint) is False
    assert await _rows(DocumentPage, target) == []


async def test_the_workers_hash_of_the_file_is_recorded_and_used(client, index):
    await _processed_source(await _collection(), index)
    target = await _document(await _collection(), content_hash=None)

    assert await _begin(client, target, PipelineStage.EXTRACTION, content_hash=FILE) is True

    async with async_session_factory() as session:
        assert (await session.get(Document, target)).content_hash == FILE


# -- what each stage copies ---------------------------------------------------------------------


async def test_the_pages_and_their_screenshots_are_copied_under_the_documents_own_keys(client, index):
    await _processed_source(await _collection(), index)
    target = await _document(await _collection())

    assert await _begin(client, target, PipelineStage.EXTRACTION) is True

    pages = await _rows(DocumentPage, target, order=DocumentPage.page_number)
    assert [(page.page_number, page.content) for page in pages] == [(1, "page one"), (2, "page two")]
    own_key = f"screenshots/{target}/page-1.png"
    assert pages[0].screenshot == own_key and pages[1].screenshot is None
    assert index["copied"] == [("shots/one.png", own_key)]
    stage = await _stage(target, PipelineStage.EXTRACTION)
    assert stage.completed_at is not None and stage.source_document_id is not None


async def test_the_chunks_are_copied_with_new_ids_and_their_vectors_without_embedding_again(client, index):
    source_collection, target_collection = await _collection(), await _collection()
    source = await _processed_source(source_collection, index)
    target = await _document(target_collection)

    assert await _begin(client, target, PipelineStage.CHUNKS) is True

    copied = await _rows(Chunk, target, order=Chunk.index)
    assert [chunk.text for chunk in copied] == ["chunk 0", "chunk 1", "chunk 2"]
    assert not {chunk.id for chunk in copied} & {chunk.id for chunk in await _rows(Chunk, source)}
    ((written_collection, points, model),) = index["points"]
    assert written_collection == target_collection and model == "model-a"
    assert [(kind, new_id, text, embedding) for kind, new_id, text, embedding in points] == [
        ("chunk", chunk.id, f"chunk {chunk.index}", [float(chunk.index), 0.5]) for chunk in copied
    ]
    assert index["embedded"] == []
    # Each copied point is written with the copy's own document (#468).
    assert index["documents"] == [{chunk.id: target for chunk in copied}]


async def test_a_vector_made_with_another_model_is_made_again_from_its_text(client, index):
    await _processed_source(await _collection(model="model-a"), index)
    target = await _document(await _collection(model="model-b"))

    assert await _begin(client, target, PipelineStage.CHUNKS) is True

    ((_, points, model),) = index["points"]
    assert model == "model-b" and {text for _, _, text, _ in points} == {"chunk 0", "chunk 1", "chunk 2"}
    assert all(embedding == [9.0, 9.0] for _, _, _, embedding in points)
    assert {text for _, text in index["embedded"]} == {"chunk 0", "chunk 1", "chunk 2"}


async def test_a_chunk_with_no_vector_at_the_source_has_none_here_either(client, index):
    source = await _processed_source(await _collection(), index)
    for chunk in await _rows(Chunk, source):
        if chunk.index == 1:
            del index["vectors"][chunk.id]
    target = await _document(await _collection())

    assert await _begin(client, target, PipelineStage.CHUNKS) is True

    assert len(await _rows(Chunk, target)) == 3
    ((_, points, _),) = index["points"]
    assert [text for _, _, text, _ in points] == ["chunk 0", "chunk 2"]


async def test_a_copied_summary_keeps_the_pages_it_was_made_from(client, index):
    source = await _processed_source(await _collection(), index)
    async with async_session_factory() as session:
        (await session.get(Document, source)).summary_pages = [[1, 10], [90, 100]]
        await session.commit()
    target = await _document(await _collection())

    assert await _begin(client, target, PipelineStage.SUMMARY) is True

    async with async_session_factory() as session:
        assert (await session.get(Document, target)).summary_pages == [[1, 10], [90, 100]]


async def test_the_summary_is_copied_with_its_vector(client, index):
    await _processed_source(await _collection(), index)
    target_collection = await _collection()
    target = await _document(target_collection)

    assert await _begin(client, target, PipelineStage.SUMMARY) is True

    async with async_session_factory() as session:
        assert (await session.get(Document, target)).summary == "The summary."
    ((collection_id, points, _),) = index["points"]
    assert collection_id == target_collection
    assert points == [("summary", target, "The summary.", [7.0, 7.0])]


async def test_only_the_pairs_the_pipeline_generated_are_copied(client, index):
    """The validated and the manual pairs are a person's work, in the source's collection."""
    source_collection, target_collection = await _collection(), await _collection()
    await _processed_source(source_collection, index)
    target = await _document(target_collection)

    assert await _begin(client, target, PipelineStage.QA, expected=["window:1-2"]) is True

    (pair,) = await _rows(QaPair, target)
    assert (pair.question, pair.collection_id, pair.generation_key) == ("Generated?", target_collection, "window:1-2")
    assert (pair.origin, pair.validated, pair.source_page, pair.source_excerpt) == (
        QaOrigin.GENERATED,
        False,
        1,
        "passage",
    )
    # Where the passage is in its page (#351): the copy has the same text, so the same place.
    assert (pair.source_start, pair.source_end) == (12, 19)
    assert pair.source_chunk_id is None
    assert [(qa_id, embedding) for qa_id, embedding, _ in index["qa_points"]] == [(pair.id, [3.0, 3.0])]
    assert index["embedded"] == []


async def test_the_entities_and_relations_are_copied_into_the_documents_collection(client, index):
    await _processed_source(await _collection(), index)
    target_collection = await _collection()
    target = await _document(target_collection)

    assert await _begin(client, target, PipelineStage.ENTITIES, expected=["pages:1-2"]) is True

    async with async_session_factory() as session:
        entities = {
            entity.name: entity.mentions
            for entity in (await session.execute(select(Entity).where(Entity.collection_id == target_collection)))
            .scalars()
            .all()
        }
        relations = (await session.execute(select(Relation).where(Relation.document_id == target))).scalars().all()
    assert entities == {"Acme Corp": 2, "Alice": 1}
    assert [(relation.type, relation.window_key) for relation in relations] == [("works_at", "pages:1-2")]


async def test_a_copy_in_the_same_collection_adds_up_like_any_other_document(client, index):
    collection_id = await _collection()
    await _processed_source(collection_id, index)
    target = await _document(collection_id)

    assert await _begin(client, target, PipelineStage.ENTITIES, expected=["pages:1-2"]) is True

    async with async_session_factory() as session:
        entities = (await session.execute(select(Entity).where(Entity.collection_id == collection_id))).scalars().all()
    assert {entity.name: entity.mentions for entity in entities} == {"Acme Corp": 4, "Alice": 2}


async def test_the_tags_are_copied(client, index):
    await _processed_source(await _collection(), index)
    target = await _document(await _collection())

    assert await _begin(client, target, PipelineStage.TAGS) is True

    assert sorted(tag.tag for tag in await _rows(DocumentTag, target)) == ["contrat", "legal"]


async def test_each_stage_is_reused_on_its_own(client, index):
    """The source completed the summary and the pairs under another fingerprint than this document's
    settings give: those are computed, the stages that match are not."""
    await _processed_source(await _collection(), index)
    target = await _document(await _collection())

    reused = {
        stage: await _begin(
            client,
            target,
            stage,
            fingerprint="a-different-one" if stage in (PipelineStage.SUMMARY, PipelineStage.TAGS) else None,
            expected=PIECES.get(stage, []),
        )
        for stage in PipelineStage
    }

    assert reused == {
        PipelineStage.EXTRACTION: True,
        PipelineStage.CHUNKS: True,
        PipelineStage.SUMMARY: False,
        PipelineStage.QA: True,
        PipelineStage.ENTITIES: True,
        PipelineStage.TAGS: False,
    }


# -- a copy stands on its own ---------------------------------------------------------------------


async def test_deleting_the_source_leaves_the_copy_as_it_is(client, index):
    source_collection, target_collection = await _collection(), await _collection()
    source = await _processed_source(source_collection, index)
    target = await _document(target_collection)
    for stage in (PipelineStage.EXTRACTION, PipelineStage.CHUNKS, PipelineStage.QA, PipelineStage.ENTITIES):
        assert await _begin(client, target, stage, expected=PIECES.get(stage, [])) is True

    async with async_session_factory() as session:
        await DocumentUploadService(session).delete_document(source_collection, USER, source)

    assert len(await _rows(DocumentPage, target)) == 2 and len(await _rows(Chunk, target)) == 3
    assert [pair.question for pair in await _rows(QaPair, target)] == ["Generated?"]
    # Its screenshot is its own: deleting the source removed the source's object, not this one.
    assert f"screenshots/{target}/page-1.png" not in index["deleted_objects"]
    assert (await _stage(target, PipelineStage.EXTRACTION)).source_document_id is None
    async with async_session_factory() as session:
        entities = (await session.execute(select(Entity).where(Entity.collection_id == target_collection))).scalars()
        assert {entity.name: entity.mentions for entity in entities} == {"Acme Corp": 2, "Alice": 1}


async def test_a_copy_that_fails_leaves_nothing_and_the_worker_computes_the_stage(client, index):
    await _processed_source(await _collection(), index)
    target_collection = await _collection()
    target = await _document(target_collection)
    index["read_error"] = RuntimeError("Qdrant is down")

    assert await _begin(client, target, PipelineStage.CHUNKS) is False

    assert await _rows(Chunk, target) == []
    stage = await _stage(target, PipelineStage.CHUNKS)
    assert stage.completed_at is None and stage.source_document_id is None


async def test_a_copy_that_fails_after_writing_vectors_removes_them(client, index, monkeypatch):
    await _processed_source(await _collection(), index)
    target = await _document(await _collection())

    def fail(*args, **kwargs):
        raise RuntimeError("storage is down")

    # The pages are copied, then the screenshot object cannot be: what was copied before is undone.
    monkeypatch.setattr("app.core.storage.copy_object", fail)

    assert await _begin(client, target, PipelineStage.EXTRACTION) is False

    assert await _rows(DocumentPage, target) == []


# -- a stage run in pieces is complete when every piece is -------------------------------------------


async def test_the_windows_of_a_stage_complete_it_as_they_are_written(client, index):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    assert await _begin(client, document_id, PipelineStage.QA, expected=["window:1-2", "window:2-3"]) is False

    async def write(window):
        return await client.put(
            f"/api/internal/collections/{collection_id}/qa-pairs/generated",
            headers=_headers(),
            json={"document_id": str(document_id), "key": window, "pairs": [{"question": "Q?", "answer": "A."}]},
        )

    await write("window:1-2")
    assert (await _stage(document_id, PipelineStage.QA)).completed_at is None
    await write("window:2-3")
    assert (await _stage(document_id, PipelineStage.QA)).completed_at is not None


async def test_a_replayed_window_does_not_complete_a_stage_on_its_own(client, index):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    await _begin(client, document_id, PipelineStage.QA, expected=["window:1-2", "window:2-3"])

    for _ in range(2):
        await client.put(
            f"/api/internal/collections/{collection_id}/qa-pairs/generated",
            headers=_headers(),
            json={"document_id": str(document_id), "key": "window:1-2", "pairs": []},
        )

    assert (await _stage(document_id, PipelineStage.QA)).completed_at is None


async def test_the_entity_windows_complete_their_stage_too(client, index):
    document_id = await _document(await _collection())
    await _begin(client, document_id, PipelineStage.ENTITIES, expected=["pages:1-2"])

    await client.put(
        f"/api/internal/documents/{document_id}/entity-windows/pages:1-2",
        headers=_headers(),
        json={"entities": [{"name": "Acme", "type": "lieu"}]},
    )

    assert (await _stage(document_id, PipelineStage.ENTITIES)).completed_at is not None


async def test_a_stage_that_started_again_forgets_what_it_had_done(client, index):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    await _begin(client, document_id, PipelineStage.EXTRACTION)
    await client.post(f"/api/internal/documents/{document_id}/stages/extraction/done", headers=_headers(), json={})
    assert (await _stage(document_id, PipelineStage.EXTRACTION)).completed_at is not None

    await _begin(client, document_id, PipelineStage.EXTRACTION, fingerprint="new-fingerprint")

    stage = await _stage(document_id, PipelineStage.EXTRACTION)
    assert stage.completed_at is None and stage.fingerprint == "new-fingerprint"


# -- a document that goes away, or is redone, is no source anymore ------------------------------------


async def test_a_document_that_is_reprocessed_is_no_longer_a_source(client, index):
    collection_id = await _collection()
    source = await _processed_source(collection_id, index)
    async with async_session_factory() as session:
        document = await session.get(Document, source)
        with patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=lambda _id, bulk=False, **_: str(uuid.uuid4()),
        ):
            await DocumentUploadService(session).reprocess(document, "dev-user")
    target = await _document(await _collection())

    assert await _begin(client, target, PipelineStage.EXTRACTION) is False
    assert (await _rows(DocumentStage, source)) == []


async def test_a_user_never_sees_where_a_result_came_from(client, index):
    source_collection = await _collection()
    await _processed_source(source_collection, index)
    target_collection = await _collection()
    target = await _document(target_collection)
    await _begin(client, target, PipelineStage.EXTRACTION)

    from app.core.security.factory import get_current_user

    app.dependency_overrides[get_current_user] = lambda: USER
    try:
        detail = (await client.get(f"/api/collections/{target_collection}/documents/{target}")).text
        listed = (await client.get(f"/api/collections/{target_collection}/documents")).text
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    for shown in (detail, listed):
        assert str(source_collection) not in shown and "source" not in shown and "fingerprint" not in shown


# -- the endpoints -------------------------------------------------------------------------------------


async def test_beginning_a_stage_of_an_unknown_document(client, index):
    response = await client.post(
        f"/api/internal/documents/{uuid.uuid4()}/stages/chunks/begin",
        headers=_headers(),
        json={"fingerprint": "chunks-fingerprint"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "path, body",
    [
        ("stages/nonsense/begin", {"fingerprint": "chunks-fingerprint"}),
        ("stages/chunks/begin", {"fingerprint": "short"}),
        ("stages/chunks/begin", {"fingerprint": "chunks-fingerprint", "content_hash": "not-a-hash"}),
    ],
)
async def test_a_malformed_stage_call_is_refused(client, index, path, body):
    document_id = await _document(await _collection())

    response = await client.post(f"/api/internal/documents/{document_id}/{path}", headers=_headers(), json=body)

    assert response.status_code == 422


async def test_the_stage_calls_need_the_workers_key(client, index):
    document_id = await _document(await _collection())

    response = await client.post(
        f"/api/internal/documents/{document_id}/stages/chunks/begin", json={"fingerprint": "chunks-fingerprint"}
    )

    assert response.status_code == 401
