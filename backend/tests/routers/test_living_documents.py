import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.task import Task

SERVICE = "app.services.living_document_service"
ODT = "application/vnd.oasis.opendocument.text"


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


@contextmanager
def _mocked_io():
    with (
        patch(f"{SERVICE}.storage.put_object") as put,
        patch(f"{SERVICE}.storage.delete_objects") as delete_objects,
        patch(f"{SERVICE}.vector_store.delete_document_embeddings") as delete_vectors,
        patch(f"{SERVICE}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())) as enqueue,
    ):
        yield {"put": put, "delete_objects": delete_objects, "delete_vectors": delete_vectors, "enqueue": enqueue}


async def _create_collection(client) -> str:
    return (await client.post("/api/collections")).json()["id"]


async def _create_living(client, collection_id: str, filename: str = "procedure.odt") -> dict:
    with _mocked_io():
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": (filename, b"v1", ODT)},
        )
    assert response.status_code == 201
    return response.json()


async def test_create_living_document_stores_first_revision_and_queues_processing(client):
    collection_id = await _create_collection(client)

    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": ("procedure.odt", b"v1", ODT)},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "living"
    assert body["type"] == "file"
    assert body["status"] == "pending"
    io["put"].assert_called_once()
    io["enqueue"].assert_called_once_with(body["id"])

    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{body['id']}/revisions")).json()
    assert len(revisions) == 1
    assert revisions[0]["number"] == 1
    assert revisions[0]["format"] == "odt"
    assert revisions[0]["origin"] == "upload"
    assert revisions[0]["is_current"] is True

    detail = (await client.get(f"/api/collections/{collection_id}/documents/{body['id']}")).json()
    assert detail["kind"] == "living"
    assert detail["current_revision"] == 1


async def test_create_living_document_accepts_markdown(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id, "notes.md")
    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert revisions[0]["format"] == "md"


async def test_create_living_document_rejects_other_formats(client):
    collection_id = await _create_collection(client)
    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 415
    io["put"].assert_not_called()
    assert (await client.get(f"/api/collections/{collection_id}/documents")).json() == []


async def test_replace_appends_a_revision_and_reindexes_that_document_only(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)

    with _mocked_io() as io:
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            params={"base_revision": 1},
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    io["delete_vectors"].assert_called_once()
    assert str(io["delete_vectors"].call_args.args[1]) == created["id"]
    io["enqueue"].assert_called_once_with(created["id"])

    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert [(r["number"], r["filename"], r["is_current"]) for r in revisions] == [
        (2, "procedure-v2.odt", True),
        (1, "procedure.odt", False),
    ]
    # The document keeps its identity and name across revisions.
    detail = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}")).json()
    assert detail["id"] == created["id"]
    assert detail["name"] == "procedure.odt"
    assert detail["current_revision"] == 2


async def test_replace_rejects_a_different_format(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io() as io:
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            params={"base_revision": 1},
            files={"file": ("procedure.md", b"# v2", "text/markdown")},
        )
    assert response.status_code == 422
    io["put"].assert_not_called()
    io["enqueue"].assert_not_called()


async def test_replace_on_a_standard_document_returns_409(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="task-id"),
    ):
        standard = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("plain.odt", b"data", ODT)},
            )
        ).json()
    assert standard["kind"] == "standard"

    with _mocked_io():
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{standard['id']}/content",
            params={"base_revision": 1},
            files={"file": ("plain.odt", b"data2", ODT)},
        )
        revisions = await client.get(f"/api/collections/{collection_id}/documents/{standard['id']}/revisions")
    assert response.status_code == 409
    assert revisions.status_code == 409


async def test_restore_appends_a_revision_pointing_at_the_old_file(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            params={"base_revision": 1},
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/{created['id']}/revisions/1/restore",
            params={"base_revision": 2},
        )

    assert response.status_code == 200
    # Restoring re-uses revision 1's file: nothing new is uploaded, but the document is reprocessed.
    io["put"].assert_not_called()
    io["enqueue"].assert_called_once_with(created["id"])
    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert [r["number"] for r in revisions] == [3, 2, 1]
    assert revisions[0]["origin"] == "restore"
    assert revisions[0]["restored_from_number"] == 1
    assert revisions[0]["filename"] == "procedure.odt"
    assert revisions[0]["is_current"] is True


async def test_restore_unknown_revision_returns_404(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        response = await client.post(
            f"/api/collections/{collection_id}/documents/{created['id']}/revisions/9/restore",
            params={"base_revision": 1},
        )
    assert response.status_code == 404


async def test_unknown_document_returns_404(client):
    collection_id = await _create_collection(client)
    with _mocked_io():
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{uuid.uuid4()}/content",
            params={"base_revision": 1},
            files={"file": ("a.odt", b"x", ODT)},
        )
    assert response.status_code == 404


async def test_deleting_a_living_document_removes_every_revision_file(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            params={"base_revision": 1},
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings"),
    ):
        response = await client.delete(f"/api/collections/{collection_id}/documents/{created['id']}")

    assert response.status_code == 204
    (deleted_keys,), _ = mock_delete.call_args
    assert len(deleted_keys) == 2
    assert any(key.endswith("procedure.odt") for key in deleted_keys)
    assert any(key.endswith("procedure-v2.odt") for key in deleted_keys)


async def test_only_the_collection_owner_can_use_living_documents(client):
    def _as_user(user_id: str):
        def override() -> RequestContext:
            return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

        return override

    app.dependency_overrides[get_current_user] = _as_user("user-a")
    try:
        collection_id = await _create_collection(client)
        created = await _create_living(client, collection_id)

        app.dependency_overrides[get_current_user] = _as_user("user-b")
        with _mocked_io():
            replace = await client.put(
                f"/api/collections/{collection_id}/documents/{created['id']}/content",
                params={"base_revision": 1},
                files={"file": ("procedure.odt", b"x", ODT)},
            )
            listing = await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")
        assert replace.status_code == 404
        assert listing.status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]


# --- Soft edit lock and revision check (#170) ---


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

    return override


def _doc_url(collection_id: str, document_id: str, suffix: str = "") -> str:
    return f"/api/collections/{collection_id}/documents/{document_id}{suffix}"


LOCK_HEADER = "X-Document-Lock-Token"


async def _replace(client, collection_id, document_id, *, base_revision, token=None, name="v.odt"):
    return await client.put(
        _doc_url(collection_id, document_id, "/content"),
        params={"base_revision": base_revision},
        headers={LOCK_HEADER: token} if token else {},
        files={"file": (name, b"new", ODT)},
    )


async def test_acquire_lock_shows_the_holder_and_blocks_a_second_acquisition(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)

    grant = await client.post(_doc_url(collection_id, created["id"], "/lock"))
    assert grant.status_code == 200
    assert grant.json()["token"]
    assert grant.json()["held_by_me"] is True

    status_ = (await client.get(_doc_url(collection_id, created["id"], "/lock"))).json()
    assert status_["held_by_me"] is True
    assert "token" not in status_
    detail = (await client.get(_doc_url(collection_id, created["id"]))).json()
    assert detail["lock"]["expires_at"] == status_["expires_at"]

    # Same user, no token (another tab): still refused, and told it's their own session.
    second = await client.post(_doc_url(collection_id, created["id"], "/lock"))
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "document_locked"
    assert second.json()["detail"]["held_by_me"] is True


async def test_a_write_without_the_token_is_refused_while_locked(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    await client.post(_doc_url(collection_id, created["id"], "/lock"))

    with _mocked_io() as io:
        response = await _replace(client, collection_id, created["id"], base_revision=1)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_locked"
    io["put"].assert_not_called()  # refused before anything was uploaded
    io["enqueue"].assert_not_called()


async def test_a_write_with_the_token_succeeds_and_releases_the_lock(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    token = (await client.post(_doc_url(collection_id, created["id"], "/lock"))).json()["token"]

    with _mocked_io():
        response = await _replace(client, collection_id, created["id"], base_revision=1, token=token)

    assert response.status_code == 200
    assert (await client.get(_doc_url(collection_id, created["id"], "/lock"))).json() is None
    assert (await client.get(_doc_url(collection_id, created["id"]))).json()["lock"] is None


async def test_a_stale_base_revision_is_a_conflict(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await _replace(client, collection_id, created["id"], base_revision=1, name="v2.odt")

    with _mocked_io() as io:
        response = await _replace(client, collection_id, created["id"], base_revision=1, name="v3.odt")

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "revision_conflict", "current_revision": 2}
    io["put"].assert_not_called()
    revisions = (await client.get(_doc_url(collection_id, created["id"], "/revisions"))).json()
    assert [r["number"] for r in revisions] == [2, 1]


async def test_restore_is_subject_to_the_lock_and_the_revision_check(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await _replace(client, collection_id, created["id"], base_revision=1, name="v2.odt")
    restore = _doc_url(collection_id, created["id"], "/revisions/1/restore")

    with _mocked_io():
        stale = await client.post(restore, params={"base_revision": 1})
        token = (await client.post(_doc_url(collection_id, created["id"], "/lock"))).json()["token"]
        locked = await client.post(restore, params={"base_revision": 2})
        ok = await client.post(restore, params={"base_revision": 2}, headers={LOCK_HEADER: token})

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    assert locked.status_code == 409
    assert locked.json()["detail"]["code"] == "document_locked"
    assert ok.status_code == 200


async def test_an_expired_lock_is_treated_as_no_lock(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)

    with patch(f"{SERVICE}._document_settings.DOCUMENT_LOCK_TTL_SECONDS", -1):
        await client.post(_doc_url(collection_id, created["id"], "/lock"))

    assert (await client.get(_doc_url(collection_id, created["id"], "/lock"))).json() is None
    # Anyone can take it again, and write without a token, once it has expired.
    with _mocked_io():
        assert (await _replace(client, collection_id, created["id"], base_revision=1)).status_code == 200
    assert (await client.post(_doc_url(collection_id, created["id"], "/lock"))).status_code == 200


async def test_renew_extends_a_live_lock_and_refuses_an_expired_one(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    grant = (await client.post(_doc_url(collection_id, created["id"], "/lock"))).json()

    renewed = await client.put(_doc_url(collection_id, created["id"], "/lock"), headers={LOCK_HEADER: grant["token"]})
    assert renewed.status_code == 200
    assert renewed.json()["expires_at"] >= grant["expires_at"]

    wrong = await client.put(_doc_url(collection_id, created["id"], "/lock"), headers={LOCK_HEADER: "nope"})
    assert wrong.status_code == 409
    assert wrong.json()["detail"] == {"code": "lock_lost"}

    # A lock that already expired can't be resurrected by renewing it.
    await client.delete(_doc_url(collection_id, created["id"], "/lock"), headers={LOCK_HEADER: grant["token"]})
    with patch(f"{SERVICE}._document_settings.DOCUMENT_LOCK_TTL_SECONDS", -1):
        expired = (await client.post(_doc_url(collection_id, created["id"], "/lock"))).json()
    late = await client.put(_doc_url(collection_id, created["id"], "/lock"), headers={LOCK_HEADER: expired["token"]})
    assert late.status_code == 409
    assert late.json()["detail"] == {"code": "lock_lost"}


async def test_release_needs_the_token_or_force_and_is_idempotent(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    url = _doc_url(collection_id, created["id"], "/lock")

    assert (await client.delete(url)).status_code == 204  # nothing held: no-op
    grant = (await client.post(url)).json()

    assert (await client.delete(url)).status_code == 409  # no token, no force
    assert (await client.delete(url, headers={LOCK_HEADER: "nope"})).status_code == 409
    assert (await client.get(url)).json() is not None

    assert (await client.delete(url, headers={LOCK_HEADER: grant["token"]})).status_code == 204
    assert (await client.get(url)).json() is None

    await client.post(url)
    assert (await client.delete(url, params={"force": "true"})).status_code == 204
    assert (await client.get(url)).json() is None


async def test_lock_routes_reject_a_standard_document_and_a_foreign_collection(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="task-id-lock"),
    ):
        standard = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("plain.odt", b"data", ODT)},
            )
        ).json()
    assert (await client.post(_doc_url(collection_id, standard["id"], "/lock"))).status_code == 409

    app.dependency_overrides[get_current_user] = _as_user("someone-else")
    try:
        assert (await client.post(_doc_url(collection_id, standard["id"], "/lock"))).status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]


# --- Download and Markdown creation from scratch (#172) ---


async def test_create_markdown_document_from_scratch(client):
    collection_id = await _create_collection(client)

    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living/markdown",
            json={"name": "Notes de réunion", "content": "# Réunion\n\nDécision : go."},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Notes de réunion.md"
    assert body["kind"] == "living"
    key, data = io["put"].call_args.args[:2]
    assert key.endswith("-Notes de réunion.md")
    assert data == "# Réunion\n\nDécision : go.".encode()
    io["enqueue"].assert_called_once_with(body["id"])

    revisions = (await client.get(_doc_url(collection_id, body["id"], "/revisions"))).json()
    assert [(r["number"], r["format"], r["origin"]) for r in revisions] == [(1, "md", "ui")]


async def test_create_markdown_document_keeps_an_existing_extension_and_drops_any_path(client):
    collection_id = await _create_collection(client)
    with _mocked_io():
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living/markdown",
            json={"name": "../../etc/Procédure.MD", "content": "x"},
        )
    assert response.status_code == 201
    assert response.json()["name"] == "Procédure.MD"


@pytest.mark.parametrize(
    "payload", [{"name": "a", "content": ""}, {"name": "  ", "content": "x"}, {"name": "a", "content": "  \n"}]
)
async def test_create_markdown_document_rejects_blank_name_or_content(client, payload):
    collection_id = await _create_collection(client)
    with _mocked_io() as io:
        response = await client.post(f"/api/collections/{collection_id}/documents/living/markdown", json=payload)
    assert response.status_code == 422
    io["put"].assert_not_called()


async def test_download_returns_the_current_revision_by_default_and_any_revision_on_request(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)  # revision 1: procedure.odt
    with _mocked_io():
        await _replace(client, collection_id, created["id"], base_revision=1, name="Procédure v2.odt")

    stored = {}

    def fake_get_object(key):
        stored.setdefault("keys", []).append(key)
        return (b"file-bytes", "application/octet-stream")

    with patch(f"{SERVICE}.storage.get_object", side_effect=fake_get_object):
        current = await client.get(_doc_url(collection_id, created["id"], "/content"))
        first = await client.get(_doc_url(collection_id, created["id"], "/content"), params={"revision": 1})

    assert current.status_code == 200
    assert current.content == b"file-bytes"
    assert current.headers["content-type"] == ODT
    assert "attachment" in current.headers["content-disposition"]
    assert "filename*=UTF-8''Proc%C3%A9dure%20v2.odt" in current.headers["content-disposition"]
    assert first.status_code == 200
    assert 'filename="procedure.odt"' in first.headers["content-disposition"]
    assert stored["keys"][0].endswith("-Procédure v2.odt")
    assert stored["keys"][1].endswith("-procedure.odt")


async def test_download_serves_markdown_with_its_media_type(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id, "notes.md")
    with patch(f"{SERVICE}.storage.get_object", return_value=(b"# Hi", "x")):
        response = await client.get(_doc_url(collection_id, created["id"], "/content"))
    assert response.headers["content-type"].startswith("text/markdown")


async def test_download_unknown_revision_standard_document_and_foreign_owner(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with patch(f"{SERVICE}.storage.get_object", return_value=(b"x", "x")):
        assert (
            await client.get(_doc_url(collection_id, created["id"], "/content"), params={"revision": 9})
        ).status_code == 404
        app.dependency_overrides[get_current_user] = _as_user("someone-else")
        try:
            assert (await client.get(_doc_url(collection_id, created["id"], "/content"))).status_code == 404
        finally:
            del app.dependency_overrides[get_current_user]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="task-id-dl"),
    ):
        standard = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("plain.odt", b"data", ODT)},
            )
        ).json()
    assert (await client.get(_doc_url(collection_id, standard["id"], "/content"))).status_code == 409
