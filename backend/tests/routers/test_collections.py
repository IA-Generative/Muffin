from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.document import Document, DocumentPage


@pytest.fixture
async def client():
    # A plain async httpx client, not the sync TestClient: TestClient runs each
    # request on its own short-lived event loop, and asyncpg connections from
    # the app's pooled engine can't be reused across loops - two consecutive
    # DB-backed requests in the same test blow up with "another operation is
    # in progress". Everything here shares this fixture's one event loop instead.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


async def test_create_and_list_collections(client):
    created = (await client.post("/api/collections")).json()
    assert created["name"] == "Nouvelle collection"
    assert created["embedding_model"] == "text-embedding-3-small"
    assert created["tags"] == []
    assert created["documents"] == []

    body = (await client.get("/api/collections")).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


async def test_get_collection_not_found_returns_404(client):
    response = await client.get("/api/collections/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_update_collection_name_description_and_tags(client):
    created = (await client.post("/api/collections")).json()

    response = await client.patch(
        f"/api/collections/{created['id']}",
        json={"name": "Projets", "description": "Notes de projet", "tags": ["a", "b", "a"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Projets"
    assert body["description"] == "Notes de projet"
    assert body["tags"] == ["a", "b"]
    assert body["description_meta"]["updated_by"] == "dev@example.com"
    assert body["tags_meta"]["updated_by"] == "dev@example.com"


async def test_delete_collection(client):
    created = (await client.post("/api/collections")).json()

    response = await client.delete(f"/api/collections/{created['id']}")
    assert response.status_code == 204


async def test_delete_collection_removes_rustfs_objects(client):
    created = (await client.post("/api/collections")).json()

    async with async_session_factory() as session:
        document = Document(collection_id=created["id"], name="report.pdf", type="file", storage_key="docs/report.pdf")
        session.add(document)
        await session.flush()
        session.add(DocumentPage(document_id=document.id, page_number=1, content="hi", screenshot="screens/p1.png"))
        await session.commit()

    with patch("app.services.collection_service.storage.delete_objects") as mock_delete:
        response = await client.delete(f"/api/collections/{created['id']}")

    assert response.status_code == 204
    mock_delete.assert_called_once()
    (deleted_keys,), _ = mock_delete.call_args
    assert set(deleted_keys) == {"docs/report.pdf", "screens/p1.png"}

    assert (await client.get(f"/api/collections/{created['id']}")).status_code == 404


async def test_pagination(client):
    for _ in range(3):
        await client.post("/api/collections")

    first_page = (await client.get("/api/collections", params={"page": 1, "page_size": 2})).json()
    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2

    second_page = (await client.get("/api/collections", params={"page": 2, "page_size": 2})).json()
    assert len(second_page["items"]) == 1


async def test_collections_are_scoped_to_their_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    created = (await client.post("/api/collections")).json()

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    try:
        assert (await client.get("/api/collections")).json()["total"] == 0
        assert (await client.get(f"/api/collections/{created['id']}")).status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]
