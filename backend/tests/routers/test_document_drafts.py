import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.document import Document
from app.models.document_draft import DocumentDraft
from app.models.document_revision import DocumentRevision
from app.models.task import Task

DRAFTS = "app.services.document_draft_service"
LIVING = "app.services.living_document_service"
ODT = "application/vnd.oasis.opendocument.text"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
API_KEY = "test-worker-key"
WORKER = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


class Io:
    """The worker queue and the object store, faked: records what was sent and stored."""

    def __init__(self) -> None:
        self.edit_jobs: list[tuple[dict, str]] = []
        self.image_jobs: list[tuple[dict, str]] = []
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail_enqueue = False

    def enqueue_edit(self, payload, task_id=None):
        if self.fail_enqueue:
            raise RuntimeError("broker down")
        self.edit_jobs.append((payload, task_id))
        return task_id

    def enqueue_images(self, payload, task_id=None):
        self.image_jobs.append((payload, task_id))
        return task_id

    def put(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = data

    def get(self, key):
        return self.objects[key], "application/octet-stream"

    def delete(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)


@pytest.fixture
def io():
    state = Io()
    with (
        patch(f"{DRAFTS}.enqueue_edit_document", state.enqueue_edit),
        patch(f"{DRAFTS}.enqueue_insert_images", state.enqueue_images),
        patch(f"{DRAFTS}.storage.put_object", state.put),
        patch(f"{DRAFTS}.storage.get_object", state.get),
        patch(f"{DRAFTS}.storage.delete_objects", state.delete),
        patch(f"{LIVING}.storage.put_object", state.put),
        patch(f"{LIVING}.storage.delete_objects", state.delete),
        patch(f"{LIVING}.vector_store.delete_document_embeddings"),
        patch(f"{LIVING}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())) as process,
    ):
        state.process = process
        yield state


async def _living(client, filename="procedure.odt") -> tuple[str, str]:
    collection_id = (await client.post("/api/collections")).json()["id"]
    with (
        patch(f"{LIVING}.storage.put_object"),
        patch(f"{LIVING}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())),
    ):
        created = await client.post(
            f"/api/collections/{collection_id}/documents/living", files={"file": (filename, b"v1", ODT)}
        )
    return collection_id, created.json()["id"]


def _url(collection_id, document_id, suffix=""):
    return f"/api/collections/{collection_id}/documents/{document_id}/draft{suffix}"


async def _create(client, collection_id, document_id, prompt="Ajoute un numéro d'urgence"):
    return await client.post(_url(collection_id, document_id), json={"prompt": prompt})


def _result(task_id, **overrides):
    body = {
        "kind": "edit",
        "draft_storage_key": "drafts/d/job.odt",
        "preview_pdf_key": "drafts/d/job.pdf",
        "operations_summary": "- Paragraphe ajouté.",
        "pending_images": [],
        "edited": True,
    }
    body.update(overrides)
    return f"/api/internal/document-drafts/{task_id}/result", body


async def _report(client, io, task_id, *, files=None, **overrides):
    url, body = _result(task_id, **overrides)
    for key, data in (files or {body["draft_storage_key"]: b"edited-odt", body["preview_pdf_key"]: b"%PDF"}).items():
        if key:
            io.objects[key] = data
    return await client.patch(url, json=body, headers=WORKER)


async def _ready(client, io, collection_id, document_id, **overrides):
    """Creates a draft and has the worker report its result - the draft is then ready."""
    await _create(client, collection_id, document_id)
    task_id = io.edit_jobs[-1][1]
    await _report(client, io, task_id, **overrides)
    return task_id


async def _draft_row(document_id) -> DocumentDraft | None:
    async with async_session_factory() as session:
        return await session.scalar(select(DocumentDraft).where(DocumentDraft.document_id == document_id))


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

    return override


# -- creating a draft ---------------------------------------------------------------------------


async def test_creating_a_draft_sends_the_job_holds_the_lock_and_records_the_task(client, io):
    collection_id, document_id = await _living(client)

    response = await _create(client, collection_id, document_id)

    assert response.status_code == 202
    body = response.json()
    assert (body["status"], body["job_kind"], body["base_revision"], body["format"]) == ("pending", "edit", 1, "odt")
    assert body["prompt"] == "Ajoute un numéro d'urgence"
    assert body["edited"] is False and body["preview"] is None and body["pending_images"] == []

    ((payload, task_id),) = io.edit_jobs
    assert payload["prompt"] == "Ajoute un numéro d'urgence"
    assert payload["base_revision"] == 1 and payload["format"] == "odt"
    assert payload["previous_draft_key"] is None
    assert payload["source_storage_key"].endswith("-procedure.odt")
    # The id the job runs under is the one stored beforehand: the worker reports back by it.
    async with async_session_factory() as session:
        assert await session.scalar(select(Task).where(Task.celery_task_id == task_id)) is not None
    row = await _draft_row(uuid.UUID(document_id))
    assert row.celery_task_id == task_id

    # The draft holds the document's lock: a manual replace is refused, and says it is "mine".
    lock = (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/lock")).json()
    assert lock["held_by_me"] is True
    refused = await client.put(
        f"/api/collections/{collection_id}/documents/{document_id}/content",
        params={"base_revision": 1},
        files={"file": ("procedure.odt", b"x", ODT)},
    )
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "document_locked"


async def test_a_second_draft_for_the_same_document_is_refused(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)

    again = await _create(client, collection_id, document_id)

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "draft_exists"
    assert len(io.edit_jobs) == 1


async def test_a_draft_needs_a_living_document_a_prompt_and_the_owner(client, io):
    collection_id, document_id = await _living(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="t-std"),
    ):
        standard = (
            await client.post(f"/api/collections/{collection_id}/documents/file", files={"file": ("a.odt", b"x", ODT)})
        ).json()

    assert (await _create(client, collection_id, standard["id"])).status_code == 409
    assert (await client.post(_url(collection_id, document_id), json={"prompt": "  "})).status_code == 422
    assert (await client.post(_url(collection_id, document_id), json={})).status_code == 422
    assert (await _create(client, collection_id, str(uuid.uuid4()))).status_code == 404

    app.dependency_overrides[get_current_user] = _as_user("someone-else")
    try:
        assert (await _create(client, collection_id, document_id)).status_code == 404
        assert (await client.get(_url(collection_id, document_id))).status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]
    assert io.edit_jobs == []


async def test_a_broker_that_refuses_the_job_leaves_no_draft_and_no_lock(client, io):
    collection_id, document_id = await _living(client)
    io.fail_enqueue = True

    with pytest.raises(RuntimeError, match="broker down"):
        await _create(client, collection_id, document_id)

    assert await _draft_row(uuid.UUID(document_id)) is None
    lock = (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/lock")).json()
    assert lock is None


async def test_a_document_someone_else_is_editing_cannot_get_a_draft(client, io):
    collection_id, document_id = await _living(client)
    grant = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/lock")
    assert grant.status_code == 200

    response = await _create(client, collection_id, document_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_locked"
    assert io.edit_jobs == []


# -- the worker reports back --------------------------------------------------------------------


async def test_the_result_of_the_job_makes_the_draft_ready_with_its_preview(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)
    job_id = io.edit_jobs[-1][1]

    reported = await _report(
        client,
        io,
        job_id,
        pending_images=[
            {"id": "img-1", "description": "Plan", "section": {"heading": "Contacts"}, "after_paragraph": 1}
        ],
    )
    assert reported.status_code == 200

    draft = (await client.get(_url(collection_id, document_id))).json()
    assert draft["status"] == "ready" and draft["edited"] is True
    assert draft["operations_summary"] == "- Paragraphe ajouté."
    assert draft["preview"] == "pdf"
    assert draft["pending_images"] == [
        {
            "id": "img-1",
            "description": "Plan",
            "section": {"heading": "Contacts"},
            "after_paragraph": 1,
            "uploaded": False,
            "inserted": False,
        }
    ]
    preview = await client.get(_url(collection_id, document_id, "/preview"))
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.content == b"%PDF"
    assert preview.headers["cache-control"] == "no-store"


async def test_a_markdown_draft_previews_as_text(client, io):
    collection_id, document_id = await _living(client, "notes.md")
    await _create(client, collection_id, document_id)
    await _report(
        client,
        io,
        io.edit_jobs[-1][1],
        draft_storage_key="drafts/d/job.md",
        preview_pdf_key=None,
        files={"drafts/d/job.md": b"# Notes\n\nNouveau"},
    )

    draft = (await client.get(_url(collection_id, document_id))).json()
    preview = await client.get(_url(collection_id, document_id, "/preview"))

    assert draft["preview"] == "markdown"
    assert preview.headers["content-type"].startswith("text/markdown")
    assert preview.content == b"# Notes\n\nNouveau"


async def test_a_draft_that_changed_nothing_has_an_explanation_and_no_preview(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)
    await _report(
        client,
        io,
        io.edit_jobs[-1][1],
        edited=False,
        preview_pdf_key=None,
        operations_summary="La liste n'est pas modifiable.",
        files={"drafts/d/job.odt": b"unchanged"},
    )

    draft = (await client.get(_url(collection_id, document_id))).json()

    assert draft["status"] == "ready" and draft["edited"] is False and draft["preview"] is None
    assert draft["operations_summary"] == "La liste n'est pas modifiable."
    assert (await client.get(_url(collection_id, document_id, "/preview"))).status_code == 409
    assert (await client.post(_url(collection_id, document_id, "/validate"))).json()["detail"]["code"] == "no_changes"


async def test_a_failed_job_marks_the_draft_failed_with_its_reason_and_it_can_be_adjusted(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)
    failed = await client.patch(
        f"/api/internal/document-drafts/{io.edit_jobs[-1][1]}/failure",
        json={"error": "Modèle injoignable"},
        headers=WORKER,
    )
    assert failed.status_code == 200

    draft = (await client.get(_url(collection_id, document_id))).json()
    assert (draft["status"], draft["error"]) == ("failed", "Modèle injoignable")

    retry = await client.post(_url(collection_id, document_id, "/adjust"), json={"prompt": "Réessaie"})
    assert retry.status_code == 202
    assert io.edit_jobs[-1][0]["previous_draft_key"] is None  # nothing to build on: from the document
    assert retry.json()["error"] is None


async def test_the_workers_reports_need_its_api_key(client, io):
    url, body = _result("anything")

    assert (await client.patch(url, json=body)).status_code in (401, 403)
    assert (await client.patch(url, json=body, headers={"X-API-Key": "wrong"})).status_code in (401, 403)


async def test_a_result_for_a_draft_that_no_longer_exists_deletes_its_orphan_files(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)
    job_id = io.edit_jobs[-1][1]
    await client.delete(_url(collection_id, document_id))  # refused while the job ran

    reported = await _report(client, io, job_id)

    assert reported.status_code == 200
    assert {"drafts/d/job.odt", "drafts/d/job.pdf"} <= set(io.deleted)
    assert io.objects == {}


# -- adjusting ----------------------------------------------------------------------------------


async def test_adjusting_builds_on_the_current_draft_and_removes_the_old_files_when_the_new_result_lands(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)
    assert (
        await client.post(_url(collection_id, document_id, "/adjust"), json={"prompt": "Plus court"})
    ).status_code == 202

    payload, new_job = io.edit_jobs[-1]
    assert payload["prompt"] == "Plus court"
    assert payload["previous_draft_key"] == "drafts/d/job.odt"
    # While it runs, the user can't pile another instruction on it.
    busy = await client.post(_url(collection_id, document_id, "/adjust"), json={"prompt": "Encore"})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "draft_busy"

    await _report(
        client,
        io,
        new_job,
        draft_storage_key="drafts/d/job2.odt",
        preview_pdf_key="drafts/d/job2.pdf",
        files={"drafts/d/job2.odt": b"v2", "drafts/d/job2.pdf": b"%PDF2"},
    )

    assert {"drafts/d/job.odt", "drafts/d/job.pdf"} <= set(io.deleted)
    draft = (await client.get(_url(collection_id, document_id))).json()
    assert draft["status"] == "ready" and draft["prompt"] == "Plus court"
    assert (await client.get(_url(collection_id, document_id, "/preview"))).content == b"%PDF2"


# -- validating and refusing --------------------------------------------------------------------


async def test_validating_promotes_the_draft_to_a_chat_revision_reindexes_and_cleans_up(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)

    response = await client.post(_url(collection_id, document_id, "/validate"))

    assert response.status_code == 200
    assert response.json()["status"] == "pending"  # being reindexed
    io.process.assert_called_once_with(document_id)
    async with async_session_factory() as session:
        revisions = (
            await session.scalars(
                select(DocumentRevision)
                .where(DocumentRevision.document_id == uuid.UUID(document_id))
                .order_by(DocumentRevision.number)
            )
        ).all()
        document = await session.get(Document, uuid.UUID(document_id))
    assert [(r.number, r.origin.value, r.filename) for r in revisions] == [
        (1, "upload", "procedure.odt"),
        (2, "chat", "procedure.odt"),
    ]
    assert io.objects[revisions[1].storage_key] == b"edited-odt"
    assert document.storage_key == revisions[1].storage_key
    # The draft and its files are gone and the document is free again.
    assert await _draft_row(uuid.UUID(document_id)) is None
    assert {"drafts/d/job.odt", "drafts/d/job.pdf"} <= set(io.deleted)
    assert (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/lock")).json() is None
    assert (await client.get(_url(collection_id, document_id))).status_code == 404


async def test_a_draft_that_is_not_ready_cannot_be_validated(client, io):
    collection_id, document_id = await _living(client)
    await _create(client, collection_id, document_id)

    response = await client.post(_url(collection_id, document_id, "/validate"))

    assert response.status_code == 409 and response.json()["detail"]["code"] == "draft_not_ready"


async def test_validating_is_refused_when_the_document_moved_on_since_the_draft_started(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)
    async with async_session_factory() as session:
        row = await session.scalar(select(DocumentDraft).where(DocumentDraft.document_id == uuid.UUID(document_id)))
        row.base_revision = 0  # as if revision 1 had been replaced since
        await session.commit()

    response = await client.post(_url(collection_id, document_id, "/validate"))

    assert response.status_code == 409 and response.json()["detail"]["code"] == "revision_conflict"
    io.process.assert_not_called()


async def test_refusing_deletes_the_draft_its_files_and_the_lock(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)

    response = await client.delete(_url(collection_id, document_id))

    assert response.status_code == 204
    assert await _draft_row(uuid.UUID(document_id)) is None
    assert {"drafts/d/job.odt", "drafts/d/job.pdf"} <= set(io.deleted)
    assert (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/lock")).json() is None
    # ...so a new edit can start straight away.
    assert (await _create(client, collection_id, document_id)).status_code == 202


# -- an abandoned draft lapses ------------------------------------------------------------------


async def _expire_the_lock(document_id):
    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        document.lock_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def test_a_draft_whose_lock_lapsed_is_cleaned_up_the_next_time_anyone_looks(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)
    await _expire_the_lock(document_id)

    assert (await client.get(_url(collection_id, document_id))).status_code == 404

    assert await _draft_row(uuid.UUID(document_id)) is None
    assert {"drafts/d/job.odt", "drafts/d/job.pdf"} <= set(io.deleted)
    assert (await _create(client, collection_id, document_id)).status_code == 202


async def test_a_lapsed_draft_is_cleaned_up_when_a_new_one_is_requested(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)
    await _expire_the_lock(document_id)

    assert (await _create(client, collection_id, document_id)).status_code == 202
    assert len(io.edit_jobs) == 2


async def test_looking_at_a_draft_keeps_it_alive(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id)
    first = (await client.get(_url(collection_id, document_id))).json()["expires_at"]

    second = (await client.get(_url(collection_id, document_id))).json()["expires_at"]

    assert second >= first
    assert (await client.get(_url(collection_id, document_id, "/preview"))).status_code == 200


# -- images -------------------------------------------------------------------------------------

SPOT = {"id": "img-1", "description": "Plan d'accès", "section": {"heading": "Contacts"}, "after_paragraph": 1}


async def _with_image_spot(client, io):
    collection_id, document_id = await _living(client)
    await _ready(client, io, collection_id, document_id, pending_images=[SPOT])
    return collection_id, document_id


def _image_url(collection_id, document_id, image_id="img-1"):
    return _url(collection_id, document_id, f"/images/{image_id}")


async def _upload(client, collection_id, document_id, data=PNG, name="plan.png", image_id="img-1"):
    return await client.put(_image_url(collection_id, document_id, image_id), files={"file": (name, data, "image/png")})


async def test_an_uploaded_image_is_stored_but_nothing_runs_until_the_user_inserts_it(client, io):
    collection_id, document_id = await _with_image_spot(client, io)

    response = await _upload(client, collection_id, document_id)

    assert response.status_code == 200
    spot = response.json()["pending_images"][0]
    assert (spot["uploaded"], spot["inserted"]) == (True, False)
    assert any(key.startswith(f"drafts/{document_id}/images/img-1-") for key in io.objects)
    assert io.image_jobs == []


async def test_inserting_runs_one_job_for_every_uploaded_image_and_the_result_marks_them_inserted(client, io):
    collection_id, document_id = await _with_image_spot(client, io)
    await _upload(client, collection_id, document_id)

    started = await client.post(_url(collection_id, document_id, "/images/insert"))

    assert started.status_code == 202
    assert (started.json()["status"], started.json()["job_kind"]) == ("pending", "images")
    payload, job_id = io.image_jobs[-1]
    assert payload["draft_storage_key"] == "drafts/d/job.odt"
    (image,) = payload["images"]
    assert (image["id"], image["description"], image["section"], image["after_paragraph"]) == (
        "img-1",
        "Plan d'accès",
        {"heading": "Contacts"},
        1,
    )
    uploaded_key = image["storage_key"]

    await _report(
        client,
        io,
        job_id,
        kind="images",
        draft_storage_key="drafts/d/job3.odt",
        preview_pdf_key="drafts/d/job3.pdf",
        operations_summary="- Image insérée.",
        files={"drafts/d/job3.odt": b"with-image", "drafts/d/job3.pdf": b"%PDF3"},
    )

    draft = (await client.get(_url(collection_id, document_id))).json()
    assert draft["status"] == "ready" and draft["job_kind"] == "images"
    assert draft["operations_summary"] == "- Paragraphe ajouté.\n- Image insérée."
    assert draft["pending_images"][0]["inserted"] is True and draft["pending_images"][0]["uploaded"] is False
    # The earlier draft and the now-useless uploaded copy are removed; the preview is the new one.
    assert {"drafts/d/job.odt", "drafts/d/job.pdf", uploaded_key} <= set(io.deleted)
    assert (await client.get(_url(collection_id, document_id, "/preview"))).content == b"%PDF3"


async def test_a_failed_image_insertion_leaves_the_draft_ready_with_the_reason(client, io):
    collection_id, document_id = await _with_image_spot(client, io)
    await _upload(client, collection_id, document_id)
    await client.post(_url(collection_id, document_id, "/images/insert"))

    await client.patch(
        f"/api/internal/document-drafts/{io.image_jobs[-1][1]}/failure",
        json={"error": "image illisible"},
        headers=WORKER,
    )

    draft = (await client.get(_url(collection_id, document_id))).json()
    assert draft["status"] == "ready"  # the previous draft is intact and can still be validated
    assert draft["error"] == "image illisible"
    assert draft["preview"] == "pdf"
    assert draft["pending_images"][0]["uploaded"] is True  # kept: the user can retry


async def test_replacing_an_uploaded_image_removes_the_previous_file(client, io):
    collection_id, document_id = await _with_image_spot(client, io)
    await _upload(client, collection_id, document_id)
    first_key = next(k for k in io.objects if "/images/" in k)

    await _upload(client, collection_id, document_id, data=PNG + b"2")

    assert first_key in io.deleted
    assert len([k for k in io.objects if "/images/" in k]) == 1


@pytest.mark.parametrize(
    ("data", "image_id", "status"),
    [(b"not an image", "img-1", 415), (b"%PDF-1.4", "img-1", 415), (PNG, "img-9", 404)],
)
async def test_an_image_upload_is_checked(client, io, data, image_id, status):
    collection_id, document_id = await _with_image_spot(client, io)

    response = await _upload(client, collection_id, document_id, data=data, image_id=image_id)

    assert response.status_code == status
    assert not [k for k in io.objects if "/images/" in k]


async def test_an_image_that_is_too_large_is_refused(client, io):
    collection_id, document_id = await _with_image_spot(client, io)

    with patch(f"{DRAFTS}.MAX_IMAGE_BYTES", 40):
        response = await _upload(client, collection_id, document_id, data=PNG + b"x" * 100)

    assert response.status_code == 415


async def test_images_cannot_be_added_to_a_markdown_draft_nor_inserted_before_one_is_uploaded(client, io):
    collection_id, document_id = await _with_image_spot(client, io)

    assert (await client.post(_url(collection_id, document_id, "/images/insert"))).json()["detail"]["code"] == (
        "no_uploaded_image"
    )

    md_collection, md_document = await _living(client, "notes.md")
    await _create(client, md_collection, md_document)
    await _report(
        client, io, io.edit_jobs[-1][1], draft_storage_key="drafts/m/job.md", preview_pdf_key=None,
        files={"drafts/m/job.md": b"# x"}, pending_images=[SPOT],
    )  # fmt: skip
    assert (await _upload(client, md_collection, md_document)).status_code == 422
    assert (await client.post(_url(md_collection, md_document, "/images/insert"))).status_code == 422


async def test_images_cannot_be_uploaded_while_a_job_is_running(client, io):
    collection_id, document_id = await _with_image_spot(client, io)
    await client.post(_url(collection_id, document_id, "/adjust"), json={"prompt": "Encore"})

    response = await _upload(client, collection_id, document_id)

    assert response.status_code == 409 and response.json()["detail"]["code"] == "draft_not_ready"
