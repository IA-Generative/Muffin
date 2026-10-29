"""The layout of a scanned page: written with it, copied when it is reused, read back (#409)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentPage, PageRegion
from app.services.result_reuse import ResultReuse
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"


def _region(type_="text", y=0.1, score=0.9, **extra):
    return {"type": type_, "score": score, "x_min": 0.1, "y_min": y, "x_max": 0.9, "y_max": y + 0.1, **extra}


# In reading order, as the worker sends them: a header, a title, a paragraph, a table, a picture, a page number.
REGIONS = [
    _region("header", 0.02),
    _region("title", 0.1, title_level=1),
    _region("text", 0.25, polygon=[(0.1, 0.25), (0.9, 0.25), (0.9, 0.35), (0.1, 0.35)]),
    _region("table", 0.4),
    _region("image", 0.6, score=0.97),
    _region("page_number", 0.88),
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
        document = Document(collection_id=collection.id, name="scan.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def _write(client, document_id, number=1, regions="absent", expect=201):
    body = {"page_number": number, "content": f"page {number}"}
    if regions != "absent":
        body["regions"] = regions
    response = await client.post(
        f"/api/internal/documents/{document_id}/pages", json=body, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == expect, response.text
    return response


async def _stored(document_id, number=1) -> list[PageRegion]:
    async with async_session_factory() as session:
        page = await session.scalar(
            select(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.page_number == number)
        )
        result = await session.execute(
            select(PageRegion).where(PageRegion.document_page_id == page.id).order_by(PageRegion.position)
        )
        return list(result.scalars())


# --- written with the page ---


async def test_the_description_of_a_region_is_kept_with_the_model_that_wrote_it(client):
    _, document_id = await _document()
    described = [{**REGIONS[4], "caption": "Un graphique en barres.", "caption_model": "Florence-2-base"}]

    await _write(client, document_id, regions=[*REGIONS[:4], *described])

    image = (await _stored(document_id))[4]
    assert (image.caption, image.caption_model) == ("Un graphique en barres.", "Florence-2-base")


async def test_a_page_is_written_with_every_region_of_its_layout_in_reading_order(client):
    _, document_id = await _document()

    await _write(client, document_id, regions=REGIONS)

    stored = await _stored(document_id)
    assert [region.type for region in stored] == ["header", "title", "text", "table", "image", "page_number"]
    assert [region.position for region in stored] == [0, 1, 2, 3, 4, 5]
    assert (stored[1].title_level, stored[2].title_level) == (1, None)
    assert (stored[4].score, stored[4].x_min, stored[4].y_max) == (0.97, 0.1, pytest.approx(0.7))
    assert stored[2].polygon == [[0.1, 0.25], [0.9, 0.25], [0.9, 0.35], [0.1, 0.35]]
    # Nothing described them (#411), and no table was read here (#410).
    assert all(region.caption is None and region.caption_model is None and region.table_id is None for region in stored)


async def test_a_page_written_again_replaces_its_regions_instead_of_adding_a_second_copy(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS)

    await _write(client, document_id, regions=REGIONS[:2])

    assert [region.type for region in await _stored(document_id)] == ["header", "title"]


async def test_a_page_written_without_the_field_keeps_its_regions_and_with_an_empty_list_loses_them(client):
    """A worker that does not send them leaves the page as it was; one that read the page another way (Tesseract)
    says it has none, and clears what a former extraction left."""
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS)

    await _write(client, document_id)
    assert len(await _stored(document_id)) == 6

    await _write(client, document_id, regions=[])
    assert await _stored(document_id) == []


async def test_the_regions_of_a_page_go_with_it_when_it_is_pruned_or_the_document_is_deleted(client):
    _, document_id = await _document()
    await _write(client, document_id, number=1, regions=REGIONS)
    await _write(client, document_id, number=2, regions=REGIONS)

    response = await client.post(
        f"/api/internal/documents/{document_id}/pages/prune", json={"keep": 1}, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    async with async_session_factory() as session:
        assert len((await session.execute(select(PageRegion))).scalars().all()) == 6
        await session.execute(delete(Document).where(Document.id == document_id))
        await session.commit()
        assert (await session.execute(select(PageRegion))).scalars().all() == []


@pytest.mark.parametrize(
    "wrong",
    [
        {"x_max": 1.7},
        {"y_min": -0.1},
        {"score": 1.5},
        {"type": ""},
        {"type": "x" * 33},
        {"title_level": 7},
        {"x_min": 0.95},  # past its maximum
        {"polygon": [(0.1, 0.1), (1.4, 0.2), (0.5, 0.5)]},
    ],
)
async def test_a_region_that_is_not_on_the_page_is_refused(client, wrong):
    _, document_id = await _document()
    await _write(client, document_id, regions=[{**REGIONS[0], **wrong}], expect=422)


async def test_a_region_type_the_backend_does_not_know_is_kept(client):
    """A pod newer than the backend may find more kinds of region: the type is free text."""
    _, document_id = await _document()
    await _write(client, document_id, regions=[_region("signature")])
    assert [region.type for region in await _stored(document_id)] == ["signature"]


async def test_too_many_regions_on_a_page_are_refused(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=[_region()] * 501, expect=422)


# --- reused with the page ---


async def test_a_page_reused_from_another_document_has_the_same_layout(client):
    collection_id, source_id = await _document()
    await _write(client, source_id, regions=REGIONS)
    async with async_session_factory() as session:
        page = await session.scalar(select(DocumentPage).where(DocumentPage.document_id == source_id))
        region = (
            (await session.execute(select(PageRegion).where(PageRegion.document_page_id == page.id))).scalars().first()
        )
        region.caption = "described"
        target = Document(collection_id=collection_id, name="copy.pdf", type="file", storage_key="k2")
        session.add(target)
        await session.commit()
        target_id = target.id

    async with async_session_factory() as session:
        source = await session.get(Document, source_id)
        target = await session.get(Document, target_id)
        await ResultReuse(session)._copy_extraction(source, target, [])
        await session.commit()

    copied = await _stored(target_id)
    assert [region.type for region in copied] == ["header", "title", "text", "table", "image", "page_number"]
    assert copied[1].title_level == 1 and copied[2].polygon is not None and copied[4].score == 0.97
    # What describes a region comes with it (the tables read from them are copied too: test_page_tables.py).
    assert copied[0].caption == "described" and copied[0].table_id is None
    assert {region.id for region in copied}.isdisjoint({region.id for region in await _stored(source_id)})


# --- read back ---


async def _get(client, collection_id, document_id, suffix="regions", **params):
    return await client.get(f"/api/collections/{collection_id}/documents/{document_id}/{suffix}", params=params)


async def test_the_layout_of_a_document_is_listed_in_page_then_reading_order(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, number=2, regions=REGIONS[:2])
    await _write(client, document_id, number=1, regions=REGIONS[:3])

    response = await _get(client, collection_id, document_id)

    assert response.status_code == 200
    body = response.json()
    assert [(region["page_number"], region["position"], region["type"]) for region in body] == [
        (1, 0, "header"),
        (1, 1, "title"),
        (1, 2, "text"),
        (2, 0, "header"),
        (2, 1, "title"),
    ]
    assert body[1]["title_level"] == 1 and body[2]["polygon"][0] == [0.1, 0.25]
    assert set(body[0]) >= {"id", "x_min", "y_min", "x_max", "y_max", "score", "caption"}


async def test_the_layout_of_one_page_and_of_some_types_can_be_asked_for(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, number=1, regions=REGIONS)
    await _write(client, document_id, number=2, regions=REGIONS)

    page = await _get(client, collection_id, document_id, "pages/2/regions")
    assert {region["page_number"] for region in page.json()} == {2} and len(page.json()) == 6

    only_tables = await _get(client, collection_id, document_id, type="table")
    assert [(r["page_number"], r["type"]) for r in only_tables.json()] == [(1, "table"), (2, "table")]

    two_types = await _get(client, collection_id, document_id, "pages/1/regions", type=["table", "image"])
    assert [region["type"] for region in two_types.json()] == ["table", "image"]

    filtered_page = await _get(client, collection_id, document_id, page=1, type="title")
    assert [(r["page_number"], r["type"]) for r in filtered_page.json()] == [(1, "title")]


async def test_a_document_without_layout_has_no_region_and_an_unknown_page_is_a_404(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, number=1)

    assert (await _get(client, collection_id, document_id)).json() == []
    assert (await _get(client, collection_id, document_id, "pages/1/regions")).json() == []
    assert (await _get(client, collection_id, document_id, "pages/9/regions")).status_code == 404
    assert (await _get(client, collection_id, document_id, page=9)).status_code == 404


async def test_the_layout_is_not_readable_by_someone_who_cannot_read_the_collection(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, regions=REGIONS)
    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

    assert (await _get(client, collection_id, document_id)).status_code == 404
    assert (await _get(client, collection_id, document_id, "pages/1/regions")).status_code == 404


async def test_the_layout_of_a_document_of_another_collection_is_not_found(client):
    collection_id, _ = await _document()
    _, other_document = await _document()
    await _write(client, other_document, regions=REGIONS)

    assert (await _get(client, collection_id, other_document)).status_code == 404
