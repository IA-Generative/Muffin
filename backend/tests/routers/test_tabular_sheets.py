"""Every sheet of a tabular file: written with its profile, read back, and cleaned up with the document (#431)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import storage
from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.document_tabular_profile import DocumentTabularProfile
from app.models.document_tabular_sheet import DocumentTabularSheet
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
def deleted(monkeypatch):
    """The RustFS keys that deleting a document or a collection asks to delete (no storage is involved)."""
    keys: list[str] = []
    monkeypatch.setattr(storage, "delete_objects", lambda found: keys.extend(found))
    return keys


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
        document = Document(
            collection_id=collection.id, name="ventes.xlsx", type="file", storage_key="docs/ventes.xlsx"
        )
        session.add(document)
        await session.commit()
        return collection.id, document.id


def _column(name, kind="text", **extra):
    return {
        "index": 0,
        "name": name,
        "type": kind,
        "non_null": 3,
        "null": 0,
        "type_counts": {kind: 3},
        "distinct": 2,
        "distinct_exact": True,
        "sample_values": ["a"],
        **extra,
    }


def _sheet(index=0, name="Ventes", **extra):
    return {
        "index": index,
        "name": name,
        "hidden": False,
        "rows": 3,
        "header_detected": True,
        "truncated": False,
        "columns": [_column("region"), _column("montant", "integer", numeric={"min": 10, "max": 30})],
        "preview": [["Nord", 10], ["Sud", 20]],
        "warnings": [],
        "table": {
            "rows": 3,
            "columns": [{"name": "region", "sql_type": "VARCHAR"}, {"name": "montant", "sql_type": "BIGINT"}],
        },
        "parquet_key": f"documents/col/doc/tables/{index}.parquet",
        **extra,
    }


def _profile(**extra):
    return {
        "row_count": 3,
        "column_count": 2,
        "columns": [
            {"name": "region", "type": "VARCHAR", "semantic_type": "dimension", "null_count": 0, "distinct_count": 2},
            {"name": "montant", "type": "BIGINT", "semantic_type": "measure", "null_count": 0, "distinct_count": 3},
        ],
        "sample_rows": [{"region": "Nord", "montant": 10}],
        "format": "xlsx",
        "measures": ["montant"],
        "dimensions": ["region"],
        "text_columns": [],
        **extra,
    }


async def _write(client, document_id, expect=201, **extra):
    response = await client.post(
        f"/api/internal/documents/{document_id}/tabular-profile",
        json=_profile(**extra),
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == expect, response.text


async def _sheets(document_id) -> list[DocumentTabularSheet]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(DocumentTabularSheet)
            .where(DocumentTabularSheet.document_id == document_id)
            .order_by(DocumentTabularSheet.index)
        )
        return list(result.scalars())


async def _read(client, collection_id, document_id):
    return await client.get(f"/api/collections/{collection_id}/documents/{document_id}/tabular-profile")


# --- written with the profile ---


async def test_the_sheets_are_kept_with_the_profile_in_their_order(client):
    _, document_id = await _document()

    await _write(client, document_id, sheets=[_sheet(1, "Clients"), _sheet(0, "Ventes")], analysis_version=1)

    sheets = await _sheets(document_id)
    assert [(s.index, s.name, s.rows) for s in sheets] == [(0, "Ventes", 3), (1, "Clients", 3)]
    assert sheets[0].columns[1]["numeric"] == {"min": 10, "max": 30}
    assert sheets[0].preview == [["Nord", 10], ["Sud", 20]]
    assert sheets[0].table["columns"][1] == {"name": "montant", "sql_type": "BIGINT"}
    assert (sheets[0].header_detected, sheets[0].truncated, sheets[0].hidden) == (True, False, False)
    assert sheets[1].parquet_key == "documents/col/doc/tables/1.parquet"
    async with async_session_factory() as session:
        profile = await session.scalar(
            select(DocumentTabularProfile).where(DocumentTabularProfile.document_id == document_id)
        )
    assert profile.analysis_version == 1


async def test_a_sheet_with_nothing_to_copy_has_no_table_and_no_key(client):
    _, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0, rows=0, table=None, parquet_key=None, columns=[])])
    [sheet] = await _sheets(document_id)
    assert (sheet.table, sheet.parquet_key, sheet.columns) == (None, None, [])


async def test_a_file_analysed_again_has_exactly_the_sheets_of_the_last_analysis(client):
    _, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0), _sheet(1, "Clients"), _sheet(2, "Stock")])

    await _write(client, document_id, sheets=[_sheet(0, "Ventes 2")])

    assert [(s.index, s.name) for s in await _sheets(document_id)] == [(0, "Ventes 2")]


async def test_a_profile_sent_without_sheets_leaves_the_sheets_it_has_and_an_empty_list_clears_them(client):
    """A worker that does not send them yet (the former one) changes nothing about them; one that finds none clears."""
    _, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0), _sheet(1, "Clients")])

    await _write(client, document_id)
    assert len(await _sheets(document_id)) == 2

    await _write(client, document_id, sheets=[])
    assert await _sheets(document_id) == []


async def test_the_profile_is_replaced_not_duplicated(client):
    _, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0)], analysis_version=1)
    await _write(client, document_id, row_count=9, sheets=[_sheet(0)], analysis_version=1)
    async with async_session_factory() as session:
        profiles = (await session.scalars(select(DocumentTabularProfile))).all()
    assert [p.row_count for p in profiles] == [9]


@pytest.mark.parametrize(
    "wrong",
    [
        {"sheets": [_sheet(0), _sheet(0, "Autre")]},  # the same index twice
        {"sheets": [_sheet(100)]},  # past the 100 sheets a file may have
        {"sheets": [_sheet(-1)]},
        {"sheets": [_sheet(0, rows=-1)]},
        {"sheets": [_sheet(0, columns=[_column(f"c{i}") for i in range(501)])]},  # past the 500 columns analysed
        {"sheets": [_sheet(0, preview=[["x"]] * 21)]},
        {"sheets": [_sheet(0, parquet_key="x" * 1025)]},
        {"sheets": [_sheet(i) for i in range(101)]},
    ],
)
async def test_sheets_that_are_not_what_the_analysis_makes_are_refused(client, wrong):
    _, document_id = await _document()
    await _write(client, document_id, expect=422, **wrong)
    assert await _sheets(document_id) == []


async def test_the_sheets_of_an_unknown_document_are_a_404(client):
    await _write(client, uuid.uuid4(), expect=404, sheets=[_sheet(0)])


# --- read back ---


async def test_the_profile_is_read_with_all_its_sheets_in_order_and_without_where_their_copy_is(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(1, "Clients"), _sheet(0, "Ventes")], analysis_version=1)

    response = await _read(client, collection_id, document_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["row_count"], body["format"], body["analysis_version"]) == (3, "xlsx", 1)
    assert body["measures"] == ["montant"]
    assert [(s["index"], s["name"], s["rows"]) for s in body["sheets"]] == [(0, "Ventes", 3), (1, "Clients", 3)]
    first = body["sheets"][0]
    assert first["columns"][1]["type"] == "integer" and first["preview"][0] == ["Nord", 10]
    assert first["table"]["columns"][0] == {"name": "region", "sql_type": "VARCHAR"}
    assert set(first) == {
        "index", "name", "hidden", "rows", "header_detected", "truncated", "columns", "preview", "warnings", "table",
    }  # fmt: skip
    assert "parquet_key" not in first  # where the copy is in storage is no business of the interface


async def test_a_profile_from_before_the_sheets_has_none_and_says_so(client):
    collection_id, document_id = await _document()
    await _write(client, document_id)

    body = (await _read(client, collection_id, document_id)).json()

    assert body["sheets"] == [] and body["analysis_version"] is None
    assert body["row_count"] == 3  # and everything else is as it was


async def test_a_document_with_no_profile_has_none(client):
    collection_id, document_id = await _document()
    response = await _read(client, collection_id, document_id)
    assert response.status_code == 200 and response.json() is None


async def test_the_sheets_are_not_readable_by_someone_who_cannot_read_the_collection(client):
    collection_id, document_id = await _document(owner="owner")
    await _write(client, document_id, sheets=[_sheet(0)])
    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

    assert (await _read(client, collection_id, document_id)).status_code == 404


async def test_the_agents_list_of_tabular_documents_still_gives_the_profile_as_it_always_did(client):
    collection_id, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0), _sheet(1, "Clients")], analysis_version=1)

    response = await client.get(
        f"/api/internal/users/dev-user/collections/{collection_id}/tabular-documents", headers={"X-API-Key": API_KEY}
    )

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["id"] == str(document_id) and entry["format"] == "xlsx"
    assert [column["name"] for column in entry["columns"]] == ["region", "montant"]


# --- gone with the document ---


async def test_the_sheets_go_with_the_document_and_so_do_their_typed_copies(client, deleted):
    collection_id, document_id = await _document()
    await _write(client, document_id, sheets=[_sheet(0), _sheet(1, "Clients")])

    response = await client.delete(f"/api/collections/{collection_id}/documents/{document_id}")

    assert response.status_code == 204
    assert await _sheets(document_id) == []
    assert "documents/col/doc/tables/0.parquet" in deleted and "documents/col/doc/tables/1.parquet" in deleted
    assert "docs/ventes.xlsx" in deleted  # and the file itself, as ever


async def test_the_single_copy_written_before_the_sheets_is_deleted_too(client, deleted):
    """That one was never deleted: it stayed in the bucket for good."""
    collection_id, document_id = await _document()
    await _write(client, document_id)  # a profile from before the sheets

    await client.delete(f"/api/collections/{collection_id}/documents/{document_id}")

    assert f"documents/{collection_id}/{document_id}.parquet" in deleted


async def test_a_document_that_is_not_tabular_asks_to_delete_no_copy(client, deleted):
    collection_id, document_id = await _document()

    await client.delete(f"/api/collections/{collection_id}/documents/{document_id}")

    assert deleted == ["docs/ventes.xlsx"]


async def test_the_copies_of_every_document_go_with_the_collection(client, deleted):
    collection_id, first = await _document()
    async with async_session_factory() as session:
        second = Document(collection_id=collection_id, name="b.csv", type="file", storage_key="docs/b.csv")
        session.add(second)
        await session.commit()
        second_id = second.id
    await _write(client, first, sheets=[_sheet(0, parquet_key="documents/c/a/tables/0.parquet")])
    await _write(client, second_id, sheets=[_sheet(0, parquet_key="documents/c/b/tables/0.parquet")])

    response = await client.delete(f"/api/collections/{collection_id}")

    assert response.status_code == 204
    assert {"documents/c/a/tables/0.parquet", "documents/c/b/tables/0.parquet"} <= set(deleted)
    assert {f"documents/{collection_id}/{first}.parquet", f"documents/{collection_id}/{second_id}.parquet"} <= set(
        deleted
    )
    async with async_session_factory() as session:
        assert (await session.scalars(select(DocumentTabularSheet))).all() == []
