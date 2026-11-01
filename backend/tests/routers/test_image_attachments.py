"""Images attached to a message for the model to read (#512): offered only when a model reads them, checked on their
bytes, theirs alone, kept until the message that carries them is sent, then the message's and its conversation's."""
# ruff: noqa: F811 - the fixtures of the image tests are imported, and used by name

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select, update

from app.core.security import worker_auth
from app.db import async_session_factory
from app.models.message_image import ORIGIN_ATTACHED, ORIGIN_GENERATED, MessageImage
from app.models.run import Run
from app.services import image_attachment_service
from tests.core.test_image_bytes import jpeg, png, webp_lossless
from tests.routers.test_images import ALICE, BOB, become, bucket, client, provider  # noqa: F401
from tests.routers.test_tools import WORKER_KEY

HEADERS = {"X-API-Key": WORKER_KEY}


@pytest.fixture(autouse=True)
async def _vision(client, monkeypatch):
    """A hub with one model that reads images, and a clean slate for what a test leaves behind."""

    async def models():
        return ["vision-1"]

    monkeypatch.setattr(image_attachment_service, "vision_models", models)
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(MessageImage))
        await session.commit()


async def stage(client, content=None, name="capture.png", content_type="image/png"):
    return await client.post(
        "/api/images/attachments", files={"file": (name, content if content is not None else png(6, 4), content_type)}
    )


async def send(client, query="Que dit ce tableau ?", image_ids=(), **fields):
    with patch("app.services.run_service.agent_runner.start"):
        return await client.post("/api/runs", json={"query": query, "image_ids": list(image_ids), **fields})


async def staged_rows() -> list[MessageImage]:
    async with async_session_factory() as session:
        return list((await session.execute(select(MessageImage))).scalars())


# --- when images are offered ---


async def test_images_are_offered_only_when_a_model_reads_them(client, monkeypatch):
    offered = (await client.get("/api/images/attachments/status")).json()

    async def none():
        return []

    monkeypatch.setattr(image_attachment_service, "vision_models", none)
    refused = await stage(client)
    status = (await client.get("/api/images/attachments/status")).json()

    assert offered["available"] is True and offered["model"] == "vision-1" and offered["max_images"] == 4
    assert offered["types"] == ["image/png", "image/jpeg", "image/webp"]
    assert status["available"] is False and status["model"] is None
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "pas_de_modele_vision"
    assert await staged_rows() == []


# --- choosing an image ---


@pytest.mark.parametrize(
    ("content", "name", "content_type", "extension"),
    [
        (png(6, 4), "a.png", "image/png", "png"),
        (jpeg(7, 5), "a.jpg", "image/jpeg", "jpg"),
        (webp_lossless(8, 6), "a.webp", "image/webp", "webp"),
    ],
)
async def test_a_raster_image_is_kept_with_the_type_read_from_its_bytes(
    client, bucket, content, name, content_type, extension
):
    # Whatever the name and the declared type say: what the bytes are is what counts.
    response = await stage(client, content, name="renamed.bin", content_type="application/octet-stream")

    body = response.json()
    assert response.status_code == 201 and body["content_type"] == content_type and body["size_bytes"] == len(content)
    [(key, (stored, _))] = bucket.items()
    assert key == f"images/attached/{body['id']}.{extension}" and stored == content
    [row] = await staged_rows()
    assert (row.origin, row.user_id, row.conversation_id, row.message_id) == (ORIGIN_ATTACHED, ALICE, None, None)


@pytest.mark.parametrize(
    "content",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<html><script>alert(1)</script></html>",
        b"GIF89a\x01\x00\x01\x00",
        b"%PDF-1.7 not an image",
        b"",
    ],
)
async def test_what_is_not_a_raster_image_is_refused_even_when_it_says_it_is_one(client, bucket, content):
    response = await stage(client, content, name="capture.png", content_type="image/png")

    assert response.status_code == 422 and response.json()["detail"]["code"] == "image_invalide"
    assert bucket == {} and await staged_rows() == []


async def test_an_image_that_is_too_heavy_or_too_large_is_refused(client, bucket, monkeypatch):
    monkeypatch.setattr(image_attachment_service._settings, "IMAGES_ATTACH_MAX_BYTES", 2000)
    heavy = await stage(client, png(6, 4) + b"\x00" * 5000)
    wide = await stage(client, png(9000, 10))

    assert heavy.status_code == 413 and heavy.json()["detail"]["code"] == "image_trop_lourde"
    assert wide.status_code == 422 and bucket == {}


async def test_only_so_many_images_may_wait_and_what_was_never_sent_is_cleaned_up(client, bucket, monkeypatch):
    monkeypatch.setattr(image_attachment_service._settings, "IMAGES_STAGED_MAX", 2)
    first = (await stage(client)).json()
    await stage(client)
    full = await stage(client)

    async with async_session_factory() as session:  # the first one was chosen two days ago and never sent
        await session.execute(
            update(MessageImage)
            .where(MessageImage.id == first["id"])
            .values(created_at=datetime.now(UTC) - timedelta(hours=48))
        )
        await session.commit()
    after = await stage(client)

    assert full.status_code == 409 and full.json()["detail"]["code"] == "trop_d_images"
    assert after.status_code == 201
    assert first["id"] not in [str(row.id) for row in await staged_rows()]
    assert not any(key.endswith(first["id"] + ".png") for key in bucket)  # its file went with it


async def test_an_image_not_sent_yet_is_shown_to_its_owner_only_and_can_be_taken_back(client, bucket):
    image = (await stage(client, png(6, 4))).json()
    url = f"/api/images/attachments/{image['id']}"

    mine = await client.get(url)
    become(BOB)
    stranger = await client.get(url)
    stranger_delete = await client.delete(url)
    become(ALICE)
    deleted = await client.delete(url)
    gone = await client.get(url)

    assert mine.status_code == 200 and mine.headers["content-type"] == "image/png"
    assert mine.headers["x-content-type-options"] == "nosniff" and mine.content == png(6, 4)
    assert stranger.status_code == 404 and stranger_delete.status_code == 404
    assert deleted.status_code == 204 and gone.status_code == 404
    assert bucket == {} and await staged_rows() == []


# --- sending them with a message ---


async def test_the_images_become_the_messages_and_are_shown_with_it_after_a_reload(client, bucket):
    image = (await stage(client, png(6, 4))).json()

    response = await send(client, image_ids=[image["id"]])
    run = response.json()
    messages = (await client.get(f"/api/conversations/{run['conversation_id']}/messages")).json()

    assert response.status_code == 202
    [user_message] = messages
    [shown] = user_message["images"]
    assert shown["id"] == image["id"] and shown["origin"] == "attached" and shown["ai_generated"] is False
    assert shown["prompt"] is None and (shown["width"], shown["height"]) == (6, 4)
    served = await client.get(f"/api/conversations/{run['conversation_id']}/images/{image['id']}")
    assert served.status_code == 200 and served.content == png(6, 4)
    [row] = await staged_rows()
    assert str(row.conversation_id) == run["conversation_id"] and row.message_id is not None


async def test_an_image_is_sent_once_and_never_reused_by_another_message(client):
    image = (await stage(client)).json()
    await send(client, image_ids=[image["id"]])

    again = await send(client, "Et celle-ci ?", image_ids=[image["id"]])

    assert again.status_code == 422 and again.json()["detail"]["code"] == "image_introuvable"


async def test_an_image_that_is_not_theirs_makes_no_message_and_no_conversation(client):
    become(BOB)
    theirs = (await stage(client)).json()
    become(ALICE)

    response = await send(client, image_ids=[theirs["id"]])

    assert response.status_code == 422 and response.json()["detail"]["code"] == "image_introuvable"
    assert (await client.get("/api/conversations")).json()["items"] == []
    [row] = await staged_rows()
    assert row.user_id == BOB and row.message_id is None  # still Bob's, untouched


async def test_a_generated_image_cannot_be_attached_as_if_it_were_the_persons_own(client):
    async with async_session_factory() as session:
        row = MessageImage(
            origin=ORIGIN_GENERATED,
            user_id=ALICE,
            prompt="un chat",
            model="m",
            s3_key="images/x/y.png",
            content_type="image/png",
            width=1,
            height=1,
            size_bytes=1,
        )
        session.add(row)
        await session.commit()
        image_id = row.id

    response = await send(client, image_ids=[str(image_id)])

    assert response.status_code == 422


async def test_a_message_carries_a_few_images_and_no_more(client, monkeypatch):
    monkeypatch.setattr(image_attachment_service._settings, "IMAGES_PER_MESSAGE", 2)
    ids = [(await stage(client)).json()["id"] for _ in range(3)]

    too_many = await send(client, image_ids=ids)
    duplicated = await send(client, image_ids=[ids[0], ids[0]])
    fine = await send(client, image_ids=ids[:2])

    assert too_many.status_code == 422 and too_many.json()["detail"]["code"] == "trop_d_images"
    assert duplicated.status_code == 422 and fine.status_code == 202


async def test_a_message_with_images_is_refused_when_no_model_reads_them_and_nothing_is_written(client, monkeypatch):
    image = (await stage(client)).json()

    async def none():
        return []

    monkeypatch.setattr(image_attachment_service, "vision_models", none)
    response = await send(client, image_ids=[image["id"]])

    assert response.status_code == 409 and response.json()["detail"]["code"] == "pas_de_modele_vision"
    assert (await client.get("/api/conversations")).json()["items"] == []
    [row] = await staged_rows()
    assert row.message_id is None


async def test_a_message_without_images_is_what_it_was(client):
    response = await send(client)

    assert response.status_code == 202
    [message] = (await client.get(f"/api/conversations/{response.json()['conversation_id']}/messages")).json()
    assert message["images"] == []


# --- what the model that writes the answer is given ---


async def run_of(client, image_ids=(), conversation_id=None, query="Que dit ce tableau ?"):
    fields = {"conversation_id": conversation_id} if conversation_id else {}
    return (await send(client, query, image_ids, **fields)).json()


async def worker_view(client, run_id) -> dict:
    response = await client.get(f"/api/internal/runs/{run_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_worker_is_told_which_images_the_answer_reads_and_fetches_their_bytes(client):
    image = (await stage(client, png(6, 4))).json()
    run = await run_of(client, [image["id"]])

    view = await worker_view(client, run["id"])
    fetched = await client.get(f"/api/internal/runs/{run['id']}/images/{image['id']}", headers=HEADERS)

    assert view["images"] == [
        {
            "id": image["id"],
            "content_type": "image/png",
            "width": 6,
            "height": 4,
            "size_bytes": len(png(6, 4)),
            "current": True,
        }
    ]
    assert fetched.status_code == 200 and fetched.content == png(6, 4)
    assert fetched.headers["content-type"] == "image/png" and fetched.headers["x-content-type-options"] == "nosniff"


async def test_a_follow_up_without_images_is_still_about_the_ones_of_the_message_before(client):
    image = (await stage(client)).json()
    first = await run_of(client, [image["id"]])

    follow_up = await run_of(client, conversation_id=first["conversation_id"], query="Et la deuxième colonne ?")
    view = await worker_view(client, follow_up["id"])

    assert [(i["id"], i["current"]) for i in view["images"]] == [(image["id"], False)]


async def test_a_message_with_its_own_images_reads_those_and_not_the_ones_before(client):
    first_image = (await stage(client)).json()
    first = await run_of(client, [first_image["id"]])
    second_image = (await stage(client, jpeg(5, 4))).json()

    second = await run_of(client, [second_image["id"]], conversation_id=first["conversation_id"], query="Et celle-ci ?")
    view = await worker_view(client, second["id"])

    assert [(i["id"], i["current"]) for i in view["images"]] == [(second_image["id"], True)]


async def test_a_message_with_no_image_in_sight_has_none_to_read(client):
    run = await run_of(client)

    assert (await worker_view(client, run["id"]))["images"] == []


async def test_the_next_turns_are_told_that_an_image_was_attached(client):
    image = (await stage(client)).json()
    first = await run_of(client, [image["id"]], query="Que dit ce tableau ?")
    second = await run_of(client, conversation_id=first["conversation_id"], query="Merci")

    history = (await worker_view(client, second["id"]))["history"]

    assert history[0]["content"] == "Que dit ce tableau ?\n[L'utilisateur avait joint 1 image(s)]"


async def test_the_worker_reads_only_the_images_attached_to_the_run_of_its_own_conversation(client):
    image = (await stage(client)).json()
    mine = await run_of(client, [image["id"]])
    other = await run_of(client, query="Une autre conversation")

    elsewhere = await client.get(f"/api/internal/runs/{other['id']}/images/{image['id']}", headers=HEADERS)
    unknown = await client.get(
        f"/api/internal/runs/{mine['id']}/images/00000000-0000-0000-0000-000000000000", headers=HEADERS
    )
    no_key = await client.get(f"/api/internal/runs/{mine['id']}/images/{image['id']}")

    assert elsewhere.status_code == 404 and unknown.status_code == 404 and no_key.status_code in (401, 403)


async def test_a_generated_image_is_not_given_to_the_worker_as_one_the_person_attached(client):
    run = await run_of(client)
    async with async_session_factory() as session:
        generated = MessageImage(
            origin=ORIGIN_GENERATED,
            user_id=ALICE,
            conversation_id=run["conversation_id"],
            prompt="un chat",
            model="m",
            s3_key="images/x/y.png",
            content_type="image/png",
            width=1,
            height=1,
            size_bytes=1,
        )
        session.add(generated)
        await session.commit()
        generated_id = generated.id

    response = await client.get(f"/api/internal/runs/{run['id']}/images/{generated_id}", headers=HEADERS)

    assert response.status_code == 404


# --- what is theirs ---


async def test_an_attached_image_goes_with_its_conversation_and_its_file_with_it(client, bucket):
    image = (await stage(client)).json()
    run = await run_of(client, [image["id"]])
    assert len(bucket) == 1

    deleted = await client.delete(f"/api/conversations/{run['conversation_id']}")

    assert deleted.status_code == 204 and bucket == {}
    async with async_session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(MessageImage))).scalar_one() == 0


async def test_an_attached_image_is_read_by_the_owner_of_the_conversation_only(client):
    image = (await stage(client)).json()
    run = await run_of(client, [image["id"]])
    url = f"/api/conversations/{run['conversation_id']}/images/{image['id']}"

    become(BOB)
    stranger = await client.get(url)
    become(ALICE)

    assert stranger.status_code == 404 and (await client.get(url)).status_code == 200
