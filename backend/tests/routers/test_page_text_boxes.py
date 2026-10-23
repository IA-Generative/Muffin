"""The positioned text of a page: written with it, copied when it is reused, and what frames a passage (#350)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentPage, PageTextBox
from app.services.result_reuse import ResultReuse
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"
CONTENT = "Bonjour tout le monde\nDeuxieme ligne"


def _word(text, x_min, x_max, start, end, y_min=0.1, y_max=0.2):
    return {
        "text": text,
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
        "char_start": start,
        "char_end": end,
    }


BOXES = [
    {
        "text": "Bonjour tout le monde",
        "x_min": 0.1,
        "y_min": 0.1,
        "x_max": 0.9,
        "y_max": 0.2,
        "char_start": 0,
        "char_end": 21,
        "words": [_word("Bonjour", 0.1, 0.3, 0, 7), _word("tout", 0.32, 0.45, 8, 12), _word("le", 0.47, 0.5, 13, 15)],
    },
    {
        "text": "Deuxieme ligne",
        "x_min": 0.1,
        "y_min": 0.3,
        "x_max": 0.6,
        "y_max": 0.4,
        "char_start": 22,
        "char_end": 36,
        "words": [_word("Deuxieme", 0.1, 0.35, 22, 30, 0.3, 0.4)],
    },
]


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _document(owner: str = "dev-user") -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="report.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def _write(client, document_id, number=1, content=CONTENT, text_boxes="absent"):
    body = {"page_number": number, "content": content}
    if text_boxes != "absent":
        body["text_boxes"] = text_boxes
    response = await client.post(
        f"/api/internal/documents/{document_id}/pages", json=body, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 201, response.text


async def _boxes(document_id, number=1) -> list[PageTextBox]:
    async with async_session_factory() as session:
        page = await session.scalar(
            select(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.page_number == number)
        )
        result = await session.execute(
            select(PageTextBox).where(PageTextBox.document_page_id == page.id).order_by(PageTextBox.position)
        )
        return list(result.scalars())


async def test_a_page_is_written_with_its_lines_and_words(client):
    _, document_id = await _document()

    await _write(client, document_id, text_boxes=BOXES)

    boxes = await _boxes(document_id)
    assert [box.text for box in boxes] == ["Bonjour tout le monde", "Deuxieme ligne"]
    assert (boxes[0].char_start, boxes[0].char_end, boxes[0].x_max) == (0, 21, 0.9)
    assert [word["text"] for word in boxes[0].words] == ["Bonjour", "tout", "le"]


async def test_a_page_written_again_replaces_its_lines_instead_of_adding_a_second_copy(client):
    _, document_id = await _document()
    await _write(client, document_id, text_boxes=BOXES)

    await _write(client, document_id, text_boxes=BOXES[:1])

    assert [box.text for box in await _boxes(document_id)] == ["Bonjour tout le monde"]


async def test_a_page_written_without_the_field_keeps_its_lines_and_with_an_empty_list_loses_them(client):
    """A worker that does not send them yet leaves the page as it was; one that says there are none clears it."""
    _, document_id = await _document()
    await _write(client, document_id, text_boxes=BOXES)

    await _write(client, document_id)
    assert len(await _boxes(document_id)) == 2

    await _write(client, document_id, text_boxes=[])
    assert await _boxes(document_id) == []


async def test_the_lines_of_a_pruned_page_go_with_it(client):
    _, document_id = await _document()
    await _write(client, document_id, number=1, text_boxes=BOXES)
    await _write(client, document_id, number=2, text_boxes=BOXES)

    response = await client.post(
        f"/api/internal/documents/{document_id}/pages/prune", json={"keep": 1}, headers={"X-API-Key": API_KEY}
    )

    assert response.status_code == 200
    async with async_session_factory() as session:
        assert len((await session.execute(select(PageTextBox))).scalars().all()) == 2


async def test_a_box_outside_the_page_is_refused(client):
    _, document_id = await _document()
    wrong = [{**BOXES[0], "x_max": 1.7}]

    response = await client.post(
        f"/api/internal/documents/{document_id}/pages",
        json={"page_number": 1, "content": CONTENT, "text_boxes": wrong},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 422


async def test_a_page_reused_from_another_document_has_the_same_lines(client):
    collection_id, source_id = await _document()
    await _write(client, source_id, text_boxes=BOXES)
    async with async_session_factory() as session:
        target = Document(collection_id=collection_id, name="copy.pdf", type="file", storage_key="k2")
        session.add(target)
        await session.commit()
        target_id = target.id

    async with async_session_factory() as session:
        source = await session.get(Document, source_id)
        target = await session.get(Document, target_id)
        await ResultReuse(session)._copy_extraction(source, target, [])
        await session.commit()

    copied = await _boxes(target_id)
    assert [box.text for box in copied] == ["Bonjour tout le monde", "Deuxieme ligne"]
    assert copied[0].words == BOXES[0]["words"] and copied[1].char_start == 22


# --- where a passage is on a page ---------------------------------------------------------------------------------


async def _highlights(client, collection_id, document_id, body, number=1):
    return await client.post(
        f"/api/collections/{collection_id}/documents/{document_id}/pages/{number}/highlights", json=body
    )


async def test_a_passage_is_framed_word_by_word_and_its_characters_are_given(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, text_boxes=BOXES)

    response = await _highlights(client, collection_id, document_id, {"text": "tout le monde ... deuxieme"})

    assert response.status_code == 200
    assert response.json() == {
        "rects": [
            {"x_min": 0.32, "y_min": 0.1, "x_max": 0.5, "y_max": 0.2},
            {"x_min": 0.1, "y_min": 0.3, "x_max": 0.35, "y_max": 0.4},
        ],
        "ranges": [{"start": 8, "end": 21}, {"start": 22, "end": 30}],
    }


async def test_an_interval_of_characters_is_framed_the_same_way(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, text_boxes=BOXES)

    response = await _highlights(client, collection_id, document_id, {"start": 0, "end": 7})

    assert response.json()["rects"] == [{"x_min": 0.1, "y_min": 0.1, "x_max": 0.3, "y_max": 0.2}]


async def test_a_passage_that_is_not_on_the_page_gives_nothing(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, text_boxes=BOXES)

    response = await _highlights(client, collection_id, document_id, {"text": "un passage qui n'y est pas"})

    assert response.json() == {"rects": [], "ranges": []}


async def test_a_page_with_no_positioned_text_gives_the_characters_but_no_rectangle(client):
    """A Markdown page, or one indexed before this existed: the text can be highlighted, nothing can be framed."""
    collection_id, document_id = await _document()
    await _write(client, document_id)

    response = await _highlights(client, collection_id, document_id, {"text": "tout le monde"})

    assert response.json() == {"rects": [], "ranges": [{"start": 8, "end": 21}]}


async def test_a_value_that_is_several_times_on_the_page_is_framed_up_to_the_limit(client):
    collection_id, document_id = await _document()
    content = "Paris est grande. Paris est belle. Paris est vieille."
    boxes = [
        {
            "text": content,
            "x_min": 0.1,
            "y_min": 0.1,
            "x_max": 0.9,
            "y_max": 0.2,
            "char_start": 0,
            "char_end": len(content),
            "words": [
                _word("Paris", 0.1 + i * 0.1, 0.18 + i * 0.1, start, start + 5) for i, start in enumerate([0, 18, 35])
            ],
        }
    ]
    await _write(client, document_id, content=content, text_boxes=boxes)

    several = await _highlights(client, collection_id, document_id, {"text": "Paris", "max_occurrences": 10})
    one = await _highlights(client, collection_id, document_id, {"text": "Paris"})

    assert len(several.json()["ranges"]) == 3 and len(several.json()["rects"]) == 3
    assert len(one.json()["ranges"]) == 1


async def test_a_request_with_neither_text_nor_interval_is_refused(client):
    collection_id, document_id = await _document()

    for body in ({}, {"text": "  "}, {"start": 5, "end": 5}, {"start": 3}):
        assert (await _highlights(client, collection_id, document_id, body)).status_code == 422


async def test_an_unknown_page_is_a_404(client):
    collection_id, document_id = await _document()

    assert (await _highlights(client, collection_id, document_id, {"text": "x y"}, number=9)).status_code == 404


async def test_the_pages_of_a_private_collection_are_not_framed_for_a_stranger(client):
    collection_id, document_id = await _document(owner="owner")
    await _write(client, document_id, text_boxes=BOXES)
    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

    response = await _highlights(client, collection_id, document_id, {"text": "tout le monde"})

    assert response.status_code == 404
