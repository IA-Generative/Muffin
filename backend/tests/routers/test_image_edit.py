"""The retouching of an image (#518): by the person - images attached in the composer, sent to the image mode - or
by the assistant, with the tool `retoucher_image`, on an image of the conversation. Same rights, quota and keeping as
a generation; the model that draws is the edit model when there is one."""
# ruff: noqa: F811 - the fixtures of the image tests are imported, and used by name

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.core import storage
from app.core.security import worker_auth
from app.db import async_session_factory
from app.models.message import Message, MessageRole
from app.models.message_image import ORIGIN_ATTACHED, ORIGIN_GENERATED, MessageImage
from app.models.run import Run
from app.models.token_usage import TokenUsage
from app.services import image_attachment_service, image_generation_service
from tests.core.test_image_bytes import png
from tests.routers.test_images import (  # noqa: F401 - the fixtures of the image tests
    ALICE,
    become,
    bucket,
    client,
    configure,
    generate,
    provider,
)
from tests.routers.test_tools import WORKER_KEY, make_run

HEADERS = {"X-API-Key": WORKER_KEY}
EDIT_REF = "internal.retoucher_image"


@pytest.fixture(autouse=True)
async def _worker(client, monkeypatch):
    async def models():
        return ["vision-1"]

    monkeypatch.setattr(image_attachment_service, "vision_models", models)
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(MessageImage))
        await session.commit()


async def stage(client, width=6, height=4) -> str:
    response = await client.post("/api/images/attachments", files={"file": ("a.png", png(width, height), "image/png")})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def call_edit(client, run_id, prompt="en noir et blanc", **arguments):
    response = await client.post(
        "/api/internal/tools/call",
        headers=HEADERS,
        json={"run_id": str(run_id), "ref": EDIT_REF, "arguments": {"prompt": prompt, **arguments}},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def offered(client, run_id) -> list[str]:
    response = await client.post("/api/internal/tools/definitions", headers=HEADERS, json={"run_id": str(run_id)})
    return [tool["name"] for tool in response.json()]


async def keep_image(conversation_id, *, origin, message_id=None, run_id=None, width=5, height=3) -> MessageImage:
    """An image already in the conversation, as a previous turn left it."""
    data = png(width, height)
    image_id = uuid.uuid4()
    key = f"images/{conversation_id}/{image_id}.png"
    storage.put_object(key, data, "image/png")
    async with async_session_factory() as session:
        image = MessageImage(
            id=image_id,
            origin=origin,
            conversation_id=conversation_id,
            message_id=message_id,
            run_id=run_id,
            user_id=ALICE,
            s3_key=key,
            content_type="image/png",
            width=width,
            height=height,
            size_bytes=len(data),
        )
        session.add(image)
        await session.commit()
        return image


async def message_of(run_id) -> uuid.UUID:
    async with async_session_factory() as session:
        return (await session.get(Run, run_id)).message_id


async def next_run(conversation_id):
    """What the person asks next, in the same conversation."""
    async with async_session_factory() as session:
        message = Message(conversation_id=conversation_id, role=MessageRole.USER, content="et en bleu ?")
        session.add(message)
        await session.flush()
        run = Run(user_id=ALICE, message_id=message.id, conversation_id=conversation_id, query="et en bleu ?")
        session.add(run)
        await session.commit()
        return run.id


# --- by the person: the image mode with images attached ---


async def test_attached_images_are_retouched_by_the_edit_model_and_become_the_requests_own(client, provider, bucket):
    await configure(client, edit_model="edit-1")
    first, second = await stage(client, 6, 4), await stage(client, 7, 5)

    response = await generate(client, "en noir et blanc", image_ids=[first, second])

    assert response.status_code == 200, response.text
    body = response.json()
    assert provider.calls == [] and len(provider.edits) == 1
    [edit] = provider.edits
    assert edit["model"] == "edit-1" and edit["prompt"] == "en noir et blanc" and "response_format" not in edit
    assert len(edit["image"]) == 2 and [name for name, _data, _type in edit["image"]]
    assert [image["id"] for image in body["user_message"]["images"]] == [first, second]
    assert body["message"]["content"].startswith("Image retouchée par IA")
    assert body["message"]["images"][0]["model"] == "edit-1"
    async with async_session_factory() as session:
        usage = (await session.execute(select(TokenUsage).where(TokenUsage.step == "image_generation"))).scalars().all()
    assert [(row.model, row.images) for row in usage] == [("edit-1", 1)]


async def test_a_single_attached_image_is_sent_alone_and_the_model_is_the_main_one_without_an_edit_model(
    client, provider
):
    await configure(client)
    only = await stage(client)

    response = await generate(client, "plus lumineux", image_ids=[only])

    assert response.status_code == 200, response.text
    [edit] = provider.edits
    assert edit["model"] == "img-1" and isinstance(edit["image"], tuple) and edit["image"][2] == "image/png"


async def test_an_unknown_image_or_too_many_stop_the_retouching_before_the_provider_is_called(client, provider):
    await configure(client)
    mine = await stage(client)

    unknown = await generate(client, "x", image_ids=[str(uuid.uuid4())])
    twice = await generate(client, "x", image_ids=[mine, mine])
    many = await generate(client, "x", image_ids=[str(uuid.uuid4()) for _ in range(20)])

    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "image_introuvable"
    assert twice.status_code == 422 and twice.json()["detail"]["code"] == "trop_d_images"
    assert many.status_code == 422
    assert provider.edits == [] and provider.calls == []


async def test_the_images_of_another_person_cannot_be_retouched(client, provider):
    await configure(client)
    mine = await stage(client)
    become("bob-user")

    refused = await generate(client, "x", image_ids=[mine])

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "image_introuvable"
    assert provider.edits == []


async def test_a_failed_retouching_leaves_the_attached_image_to_try_again(client, provider):
    from openai import APIConnectionError

    from tests.routers.test_images import REQUEST

    await configure(client)
    mine = await stage(client)
    provider.error = APIConnectionError(request=REQUEST)

    failed = await generate(client, "x", image_ids=[mine])
    provider.error = None
    again = await generate(client, "x", image_ids=[mine])

    assert failed.status_code >= 500 and again.status_code == 200, again.text


# --- by the assistant: the tool ---


async def test_the_tool_is_offered_only_with_the_function_on_and_an_image_in_the_conversation(client, provider):
    run_id, conversation_id = await make_run()
    off = await offered(client, run_id)
    await configure(client)
    without_image = await offered(client, run_id)
    await keep_image(conversation_id, origin=ORIGIN_GENERATED)
    with_image = await offered(client, run_id)

    assert "retoucher_image" not in off + without_image
    assert "generer_image" in without_image and "retoucher_image" in with_image


async def test_the_tool_retouches_the_image_attached_to_the_message_and_says_so(client, provider):
    await configure(client, edit_model="edit-1")
    run_id, conversation_id = await make_run()
    attached = await keep_image(conversation_id, origin=ORIGIN_ATTACHED, message_id=await message_of(run_id))

    result = await call_edit(client, run_id, "  en noir et blanc  ")

    assert result["ok"] is True and result["tool_name"] == "retoucher_image"
    assert "retouchée" in result["text"] and "« en noir et blanc »" in result["text"]
    [edit] = provider.edits
    assert edit["model"] == "edit-1" and edit["image"][1] == png(5, 3) and provider.calls == []
    async with async_session_factory() as session:
        made = (await session.execute(select(MessageImage).where(MessageImage.run_id == run_id))).scalars().all()
    assert [(image.origin, image.model, image.prompt) for image in made] == [
        (ORIGIN_GENERATED, "edit-1", "en noir et blanc")
    ]
    assert attached.id not in [image.id for image in made]


async def test_the_tool_retouches_the_last_generated_image_when_nothing_is_attached(client, provider):
    await configure(client)
    _first, conversation_id = await make_run()
    await keep_image(conversation_id, origin=ORIGIN_GENERATED, width=9, height=9)
    follow_up = await next_run(conversation_id)

    result = await call_edit(client, follow_up, "en bleu")

    assert result["ok"] is True
    [edit] = provider.edits
    assert edit["image"][1] == png(9, 9) and edit["model"] == "img-1"


async def test_the_source_can_be_chosen_between_the_attached_and_the_generated_one(client, provider, monkeypatch):
    monkeypatch.setattr(image_generation_service._settings, "IMAGES_PER_RUN", 5)
    await configure(client)
    run_id, conversation_id = await make_run()
    await keep_image(conversation_id, origin=ORIGIN_ATTACHED, message_id=await message_of(run_id), width=4, height=4)
    await keep_image(conversation_id, origin=ORIGIN_GENERATED, width=9, height=9)

    await call_edit(client, run_id, source="generee")
    await call_edit(client, run_id, source="jointe")
    await call_edit(client, run_id)

    assert [edit["image"][1] for edit in provider.edits] == [png(9, 9), png(4, 4), png(4, 4)]


async def test_the_tool_with_no_image_of_the_kind_asked_fails_without_calling_the_provider(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await keep_image(conversation_id, origin=ORIGIN_GENERATED)

    result = await call_edit(client, run_id, source="jointe")

    assert (result["ok"], result["code"]) == (False, "aucune_image")
    assert provider.edits == [] and provider.calls == []
    async with async_session_factory() as session:
        query = select(func.count()).select_from(MessageImage).where(MessageImage.run_id.is_not(None))
        made = (await session.execute(query)).scalar_one()
    assert made == 0


async def test_the_tool_in_a_conversation_with_no_image_is_not_available(client, provider):
    await configure(client)
    run_id, _ = await make_run()

    result = await call_edit(client, run_id)

    assert (result["ok"], result["code"]) == (False, "outil_indisponible")
    assert provider.edits == [] and provider.calls == []


async def test_the_tool_is_not_called_when_the_function_is_off(client, provider):
    run_id, conversation_id = await make_run()
    await keep_image(conversation_id, origin=ORIGIN_GENERATED)

    result = await call_edit(client, run_id)

    assert result["code"] == "outil_indisponible" and provider.edits == []


# --- the settings ---


async def test_the_edit_model_is_a_setting_that_can_be_emptied(client, provider):
    set_up = await configure(client, edit_model="  edit-1  ")
    become("root", admin=True)
    emptied = await client.patch("/api/admin/image-generation", json={"edit_model": ""})
    become(ALICE)

    assert set_up["edit_model"] == "edit-1" and emptied.json()["edit_model"] is None
