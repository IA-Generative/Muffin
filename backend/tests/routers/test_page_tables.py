"""The tables read on a scanned page: written with it, tied to their region, copied when it is reused, read (#410)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentPage, DocumentTable, PageRegion
from app.services.result_reuse import ResultReuse
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"


def _region(type_="text", y=0.1):
    return {"type": type_, "score": 0.9, "x_min": 0.1, "y_min": y, "x_max": 0.9, "y_max": y + 0.1}


REGIONS = [_region("title", 0.05), _region("table", 0.2), _region("text", 0.45), _region("table", 0.6)]


def _cell(row, col, text="", **spans):
    return {"row": row, "col": col, "text": text, **spans}


def _table(rank=1, region_position=1, **extra):
    return {
        "rank": rank,
        "region_position": region_position,
        "n_rows": 3,
        "n_cols": 2,
        "has_header": True,
        "headers": ["Année", "Dossiers"],
        "cells": [
            _cell(0, 0, "Année"),
            _cell(0, 1, "Dossiers"),
            _cell(1, 0, "2024"),
            _cell(1, 1, "1 234"),
            _cell(2, 0, "Total", col_span=1),
            _cell(2, 1, "1 234"),
        ],
        "markdown": "| Année | Dossiers |\n| --- | --- |\n| 2024 | 1 234 |\n| Total | 1 234 |",
        "html": "<table><tr><td>Année</td><td>Dossiers</td></tr></table>",
        "score": 0.92,
        "reliable": True,
        "model_version": "SLANet_plus_onnx",
        **extra,
    }


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


async def _write(client, document_id, number=1, regions="absent", tables="absent", expect=201):
    body = {"page_number": number, "content": f"page {number}"}
    if regions != "absent":
        body["regions"] = regions
    if tables != "absent":
        body["tables"] = tables
    response = await client.post(
        f"/api/internal/documents/{document_id}/pages", json=body, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == expect, response.text


async def _page_id(session, document_id, number=1):
    page = await session.scalar(
        select(DocumentPage).where(DocumentPage.document_id == document_id, DocumentPage.page_number == number)
    )
    return page.id


async def _tables(document_id, number=1) -> list[DocumentTable]:
    async with async_session_factory() as session:
        page_id = await _page_id(session, document_id, number)
        result = await session.execute(
            select(DocumentTable).where(DocumentTable.document_page_id == page_id).order_by(DocumentTable.rank)
        )
        return list(result.scalars())


async def _regions(document_id, number=1) -> list[PageRegion]:
    async with async_session_factory() as session:
        page_id = await _page_id(session, document_id, number)
        result = await session.execute(
            select(PageRegion).where(PageRegion.document_page_id == page_id).order_by(PageRegion.position)
        )
        return list(result.scalars())


# --- written with the page ---


async def test_a_page_is_written_with_its_tables_each_tied_to_the_region_it_was_read_from(client):
    _, document_id = await _document()

    await _write(client, document_id, regions=REGIONS, tables=[_table(1, 1), _table(2, 3, reliable=False)])

    tables = await _tables(document_id)
    assert [(t.rank, t.n_rows, t.n_cols, t.reliable) for t in tables] == [(1, 3, 2, True), (2, 3, 2, False)]
    assert tables[0].headers == ["Année", "Dossiers"] and tables[0].has_header
    assert tables[0].cells[3] == {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "text": "1 234"}
    assert tables[0].markdown.startswith("| Année |") and tables[0].html.startswith("<table>")
    regions = await _regions(document_id)
    assert [region.table_id for region in regions] == [None, tables[0].id, None, tables[1].id]


async def test_the_cells_keep_their_grid(client):
    _, document_id = await _document()
    merged = _table(cells=[_cell(0, 0, "Titre", col_span=2), _cell(1, 0, "a"), _cell(1, 1, "b")], n_rows=2)

    await _write(client, document_id, regions=REGIONS, tables=[merged])

    [stored] = await _tables(document_id)
    assert stored.cells[0]["text"] == "Titre" and stored.cells[0]["col_span"] == 2
    assert stored.cells[1]["col_span"] == 1


async def test_a_page_written_again_replaces_its_tables_and_their_links(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table(1, 1), _table(2, 3)])

    await _write(client, document_id, regions=REGIONS, tables=[_table(1, 3, n_rows=3)])

    tables = await _tables(document_id)
    assert [t.rank for t in tables] == [1]
    # The region the old table was read from no longer points at anything; the new one's does.
    assert [region.table_id for region in await _regions(document_id)] == [None, None, None, tables[0].id]


async def test_a_page_written_without_the_field_keeps_its_tables_and_with_an_empty_list_loses_them(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table()])

    await _write(client, document_id)
    assert len(await _tables(document_id)) == 1

    await _write(client, document_id, tables=[])
    assert await _tables(document_id) == []
    # The link went with the table; the region stays.
    assert all(region.table_id is None for region in await _regions(document_id))
    assert len(await _regions(document_id)) == 4


async def test_tables_sent_alone_are_tied_to_the_regions_the_page_already_has(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS)

    await _write(client, document_id, tables=[_table(1, 1)])

    [table] = await _tables(document_id)
    assert (await _regions(document_id))[1].table_id == table.id


async def test_a_table_whose_region_is_unknown_is_kept_without_a_link(client):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table(1, 99), _table(2, None)])

    assert len(await _tables(document_id)) == 2
    assert all(region.table_id is None for region in await _regions(document_id))


async def test_the_tables_of_a_page_go_with_it_when_it_is_pruned_or_the_document_is_deleted(client):
    _, document_id = await _document()
    await _write(client, document_id, number=1, regions=REGIONS, tables=[_table()])
    await _write(client, document_id, number=2, regions=REGIONS, tables=[_table()])

    response = await client.post(
        f"/api/internal/documents/{document_id}/pages/prune", json={"keep": 1}, headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    async with async_session_factory() as session:
        assert len((await session.execute(select(DocumentTable))).scalars().all()) == 1
        await session.execute(delete(Document).where(Document.id == document_id))
        await session.commit()
        assert (await session.execute(select(DocumentTable))).scalars().all() == []


@pytest.mark.parametrize(
    "wrong",
    [
        {"rank": 0},
        {"score": 1.2},
        {"n_rows": 0},
        {"n_rows": 1001},
        {"cells": [_cell(2, 0, "x")], "n_rows": 2},  # out of the grid
        {"cells": [_cell(0, 1, "x", col_span=2)]},  # spans past the last column
        {"markdown": "x" * 1_000_001},
        {"cells": [_cell(0, 0, "x" * 5001)]},
    ],
)
async def test_a_table_that_is_not_one_is_refused(client, wrong):
    _, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table(**wrong)], expect=422)


async def test_two_tables_of_a_page_cannot_share_a_rank(client):
    _, document_id = await _document()
    await _write(client, document_id, tables=[_table(1, 1), _table(1, 3)], expect=422)


# --- reused with the page ---


async def test_a_page_reused_from_another_document_has_the_same_tables_tied_to_its_own_regions(client):
    collection_id, source_id = await _document()
    await _write(client, source_id, regions=REGIONS, tables=[_table(1, 1), _table(2, 3, reliable=False)])
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

    copied = await _tables(target_id)
    assert [(t.rank, t.reliable, t.headers) for t in copied] == [
        (1, True, ["Année", "Dossiers"]),
        (2, False, ["Année", "Dossiers"]),
    ]
    assert copied[0].cells == (await _tables(source_id))[0].cells
    assert {t.id for t in copied}.isdisjoint({t.id for t in await _tables(source_id)})
    # Each copy is tied to the region at the same place as the source's, in the copy's own layout.
    regions = await _regions(target_id)
    assert [region.table_id for region in regions] == [None, copied[0].id, None, copied[1].id]
    assert {r.id for r in regions}.isdisjoint({r.id for r in await _regions(source_id)})


# --- read back ---


async def _get(client, collection_id, document_id, suffix="tables"):
    return await client.get(f"/api/collections/{collection_id}/documents/{document_id}/{suffix}")


async def test_the_tables_of_a_document_are_listed_without_their_content_in_page_then_reading_order(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, number=2, regions=REGIONS, tables=[_table(1, 1)])
    await _write(client, document_id, number=1, regions=REGIONS, tables=[_table(1, 1), _table(2, 3, reliable=False)])

    response = await _get(client, collection_id, document_id)

    assert response.status_code == 200
    body = response.json()
    assert [(t["page_number"], t["rank"], t["reliable"]) for t in body] == [(1, 1, True), (1, 2, False), (2, 1, True)]
    # What the page's marker says, whole: with it the agent needs nothing else.
    assert body[0]["table_id"] == f"{document_id}/p1/t1" and body[2]["table_id"] == f"{document_id}/p2/t1"
    assert body[0]["headers"] == ["Année", "Dossiers"] and (body[0]["n_rows"], body[0]["n_cols"]) == (3, 2)
    assert "cells" not in body[0] and "markdown" not in body[0]


async def test_a_table_is_read_with_its_content(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, number=3, regions=REGIONS, tables=[_table(1, 1), _table(2, 3)])

    response = await _get(client, collection_id, document_id, "pages/3/tables/2")

    assert response.status_code == 200
    body = response.json()
    assert body["table_id"] == f"{document_id}/p3/t2" and body["rank"] == 2
    assert body["markdown"].startswith("| Année |") and body["html"].startswith("<table>")
    assert body["cells"][3] == {"row": 1, "col": 1, "row_span": 1, "col_span": 1, "text": "1 234"}
    assert body["model_version"] == "SLANet_plus_onnx"


async def test_an_unknown_table_is_a_404(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table()])

    assert (await _get(client, collection_id, document_id, "pages/1/tables/2")).status_code == 404
    assert (await _get(client, collection_id, document_id, "pages/9/tables/1")).status_code == 404


async def test_a_document_without_tables_has_none(client):
    collection_id, document_id = await _document()
    await _write(client, document_id)
    assert (await _get(client, collection_id, document_id)).json() == []


async def test_the_tables_are_not_readable_by_someone_who_cannot_read_the_collection(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, regions=REGIONS, tables=[_table()])
    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

    assert (await _get(client, collection_id, document_id)).status_code == 404
    assert (await _get(client, collection_id, document_id, "pages/1/tables/1")).status_code == 404


async def test_the_table_of_a_document_of_another_collection_is_not_found(client):
    collection_id, _ = await _document()
    _, other_document = await _document()
    await _write(client, other_document, regions=REGIONS, tables=[_table()])

    assert (await _get(client, collection_id, other_document, "pages/1/tables/1")).status_code == 404


# --- what the agent reads ---


def _headers():
    return {"X-API-Key": API_KEY}


async def test_the_agent_reads_a_table_of_a_document_its_user_owns(client):
    _, document_id = await _document(owner="dev-user")
    await _write(client, document_id, regions=REGIONS, tables=[_table()])

    response = await client.get(
        f"/api/internal/users/dev-user/documents/{document_id}/pages/1/tables/1", headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["table_id"] == f"{document_id}/p1/t1" and body["markdown"].startswith("| Année |")


async def test_the_agent_does_not_read_a_table_of_a_document_its_user_does_not_own(client):
    _, document_id = await _document(owner="someone-else")
    await _write(client, document_id, regions=REGIONS, tables=[_table()])

    response = await client.get(
        f"/api/internal/users/dev-user/documents/{document_id}/pages/1/tables/1", headers=_headers()
    )

    assert response.status_code == 404


async def test_the_agent_gets_a_404_for_a_table_that_is_not_there(client):
    _, document_id = await _document(owner="dev-user")
    await _write(client, document_id, regions=REGIONS, tables=[_table()])

    response = await client.get(
        f"/api/internal/users/dev-user/documents/{document_id}/pages/1/tables/5", headers=_headers()
    )
    assert response.status_code == 404
    assert (await client.get(f"/api/internal/users/dev-user/documents/{document_id}/pages/1/tables/1")).status_code in (
        401,
        403,
    )
