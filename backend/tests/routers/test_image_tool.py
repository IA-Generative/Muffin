"""The assistant asks for an image (#518, the tool `generer_image`): offered only while the function is on and open to
the person, with the same rights, quota and keeping as the person's own request, an image that goes to the answer of its
run, and a history that remembers what it was made from."""
# ruff: noqa: F811 - the fixtures of the image tests are imported, and used by name

import json

import pytest
from openai import AuthenticationError  # noqa: E402
from sqlalchemy import delete, func, select

from app.core.security import worker_auth
from app.db import async_session_factory
from app.models.message_image import MessageImage
from app.models.run import Run
from app.models.token_usage import TokenUsage
from app.schemas.image_generation import ImageOut  # noqa: E402,F401  (the shape the run answers with)
from app.services import image_generation_service
from tests.routers.test_images import (  # noqa: F401 - the fixtures of the image tests
    ALICE,
    BOB,
    OWN_KEY,
    Provider,
    become,
    bucket,
    client,
    configure,
    generate,
    provider,
    status_error,
)
from tests.routers.test_tools import WORKER_KEY, make_run

REF = "internal.generer_image"
HEADERS = {"X-API-Key": WORKER_KEY}


@pytest.fixture(autouse=True)
async def _worker(client, monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.commit()


async def call_tool(client, run_id, prompt="un chat sur un toit", **arguments):
    response = await client.post(
        "/api/internal/tools/call",
        headers=HEADERS,
        json={"run_id": str(run_id), "ref": REF, "arguments": {"prompt": prompt, **arguments}},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def offered(client, run_id) -> list[str]:
    response = await client.post("/api/internal/tools/definitions", headers=HEADERS, json={"run_id": str(run_id)})
    return [tool["name"] for tool in response.json()]


async def images_of_run(run_id) -> list[MessageImage]:
    async with async_session_factory() as session:
        rows = await session.execute(select(MessageImage).where(MessageImage.run_id == run_id))
        return list(rows.scalars())


# --- when it is offered ---


async def test_the_tool_is_not_offered_until_the_function_is_on(client, provider):
    run_id, _ = await make_run()

    before = await offered(client, run_id)
    listed_before = [tool["name"] for tool in (await client.get("/api/tools")).json()]
    refused = await call_tool(client, run_id)
    await configure(client)
    after = await offered(client, run_id)
    listed_after = [tool["name"] for tool in (await client.get("/api/tools")).json()]

    assert "generer_image" not in before + listed_before
    assert (refused["ok"], refused["code"]) == (False, "outil_indisponible") and provider.calls == []
    assert "generer_image" in after and "generer_image" in listed_after
    assert {"calculatrice", "calcul_dates"} <= set(after)  # Muffin's other tools are still there


async def test_the_tool_is_offered_to_the_groups_allowed_only(client, provider):
    await configure(client, allowed_groups=["communication"])
    outside, _ = await make_run(ALICE, ["rh"])
    inside, _ = await make_run(ALICE, ["communication"])

    assert "generer_image" not in await offered(client, outside)
    assert "generer_image" in await offered(client, inside)
    refused = await call_tool(client, outside)
    assert refused["code"] == "outil_indisponible" and provider.calls == []


async def test_a_function_that_is_not_complete_is_not_offered(client, provider):
    become("root", admin=True)
    await client.patch("/api/admin/image-generation", json={"enabled": False, "model": ""})
    become(ALICE)
    run_id, _ = await make_run()

    assert "generer_image" not in await offered(client, run_id)


async def test_a_conversation_that_removed_the_tool_does_not_offer_it_nor_call_it(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await client.put(f"/api/conversations/{conversation_id}/tools", json={"disabled_refs": [REF]})

    assert "generer_image" not in await offered(client, run_id)
    assert (await call_tool(client, run_id))["code"] == "outil_indisponible" and provider.calls == []


# --- a call ---


async def test_a_call_makes_an_image_for_the_run_with_the_description_and_tells_the_model_what_was_done(
    client, provider, bucket
):
    await configure(client, size="1536x1024")
    run_id, conversation_id = await make_run()

    result = await call_tool(client, run_id, "  un chat sur un toit  ")

    assert result["ok"] is True and result["code"] == "ok" and result["tool_name"] == "generer_image"
    assert "« un chat sur un toit »" in result["text"] and "affichée à l'utilisateur" in result["text"]
    assert "Ne mets aucun lien" in result["text"]
    [call] = provider.calls
    assert call["prompt"] == "un chat sur un toit" and call["size"] == "1536x1024" and "response_format" not in call
    [image] = await images_of_run(run_id)
    assert image.message_id is None and image.user_id == ALICE and image.conversation_id == conversation_id
    assert [key for key in bucket] == [f"images/{conversation_id}/{image.id}.png"]


async def test_the_run_shows_the_image_before_its_answer_is_a_message(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await call_tool(client, run_id)

    run = (await client.get(f"/api/runs/{run_id}")).json()

    [image] = run["images"]
    assert image["ai_generated"] is True and image["prompt"] == "un chat sur un toit"
    served = await client.get(f"/api/conversations/{conversation_id}/images/{image['id']}")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"


async def test_the_image_goes_with_the_answer_of_the_run_and_stays_after_a_reload(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await call_tool(client, run_id)

    done = await client.patch(
        f"/api/internal/runs/{run_id}/result", headers=HEADERS, json={"answer": "Voici votre chat sur un toit."}
    )
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()

    assert done.status_code == 200, done.text
    answer = next(m for m in messages if m["role"] == "assistant")
    assert [i["prompt"] for i in answer["images"]] == ["un chat sur un toit"]
    assert (await client.get(f"/api/runs/{run_id}")).json()["images"][0]["id"] == answer["images"][0]["id"]


async def test_the_next_turns_are_told_what_image_was_made_and_from_what_description(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await call_tool(client, run_id, "un chat roux sur un toit")
    await client.patch(f"/api/internal/runs/{run_id}/result", headers=HEADERS, json={"answer": "Voilà."})
    follow_up, _ = await make_run_in(conversation_id)

    history = (await client.get(f"/api/internal/runs/{follow_up}", headers=HEADERS)).json()["history"]

    answer = next(item for item in history if item["role"] == "assistant")
    assert answer["content"].startswith("Voilà.")
    assert "Image générée par IA" in answer["content"] and "« un chat roux sur un toit »" in answer["content"]


async def make_run_in(conversation_id):
    """A run in a conversation that already has one: what the person asks next."""
    async with async_session_factory() as session:
        from app.models.message import Message, MessageRole

        message = Message(conversation_id=conversation_id, role=MessageRole.USER, content="fais-le en bleu")
        session.add(message)
        await session.flush()
        run = Run(user_id=ALICE, message_id=message.id, conversation_id=conversation_id, query="fais-le en bleu")
        session.add(run)
        await session.commit()
        return run.id, conversation_id


async def test_an_answer_with_no_image_has_none(client, provider):
    await configure(client)
    run_id, conversation_id = await make_run()
    await client.patch(f"/api/internal/runs/{run_id}/result", headers=HEADERS, json={"answer": "Bonjour."})

    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()

    assert [m["images"] for m in messages if m["role"] == "assistant"] == [[]]


# --- the same rights and quota as the person's own request ---


async def test_a_run_may_ask_for_a_few_images_and_no_more(client, provider, monkeypatch):
    monkeypatch.setattr(image_generation_service._settings, "IMAGES_PER_RUN", 2)
    await configure(client)
    run_id, _ = await make_run()

    results = [await call_tool(client, run_id, f"image {n}") for n in range(3)]

    assert [r["ok"] for r in results] == [True, True, False]
    assert results[2]["code"] == "limite_par_reponse" and len(provider.calls) == 2
    assert len(await images_of_run(run_id)) == 2


async def test_the_quota_of_the_day_is_the_persons_whether_they_ask_or_the_assistant_does(client, provider):
    await configure(client, daily_limit=2)
    run_id, _ = await make_run()

    by_button = await generate(client, "demandée par le bouton")
    by_tool = await call_tool(client, run_id, "demandée par l'assistant")
    refused_tool = await call_tool(client, run_id, "une de trop")
    refused_button = await generate(client, "une de trop aussi")

    assert by_button.status_code == 200 and by_tool["ok"] is True
    assert (refused_tool["ok"], refused_tool["code"]) == (False, "quota_depasse")
    assert refused_button.status_code == 429 and len(provider.calls) == 2


async def test_a_failed_image_counts_for_nothing_and_says_why_without_the_providers_words(client, provider):
    await configure(client, daily_limit=1)
    run_id, _ = await make_run()
    provider.error = status_error(AuthenticationError, 401, "invalid_api_key")

    failed = await call_tool(client, run_id)
    provider.error = None
    worked = await call_tool(client, run_id)

    assert (failed["ok"], failed["code"]) == (False, "cle_refusee") and "PROVIDER-TEXT" not in json.dumps(failed)
    assert worked["ok"] is True and len(await images_of_run(run_id)) == 1


async def test_the_description_is_checked_before_anything_is_called(client, provider):
    await configure(client)
    run_id, _ = await make_run()

    empty = await call_tool(client, run_id, "")
    long = await call_tool(client, run_id, "x" * 4001)
    extra = await call_tool(client, run_id, "ok", size="gigantesque")

    assert [r["code"] for r in (empty, long, extra)] == ["arguments_invalides"] * 3
    assert provider.calls == []


async def test_what_a_run_made_is_the_persons_and_counted_in_their_usage(client, provider):
    await configure(client)
    run_id, _ = await make_run()
    await call_tool(client, run_id)

    async with async_session_factory() as session:
        rows = (await session.execute(select(TokenUsage).where(TokenUsage.step == "image_generation"))).scalars().all()
        count = (await session.execute(select(func.count()).select_from(MessageImage))).scalar_one()

    assert [(row.user_id, row.images, row.pixels) for row in rows] == [(ALICE, 1, 48)] and count == 1
    become(BOB)
    other = await client.get(f"/api/runs/{run_id}")
    assert other.status_code == 404  # nobody else sees the run, nor its image


async def test_a_run_of_another_person_cannot_make_an_image_for_this_one(client, provider):
    await configure(client)
    bobs_run, _ = await make_run(BOB)

    result = await call_tool(client, bobs_run)

    # The person is read from the run: the image is Bob's, with Bob's quota, whatever the caller says.
    assert result["ok"] is True
    [image] = await images_of_run(bobs_run)
    assert image.user_id == BOB
