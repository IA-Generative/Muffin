"""The OpenAI-compatible API (#513): who may call it, the models it lists, and what a chat completion gives back."""

import asyncio
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.api_key import ApiKey
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.message import MessageRole
from app.models.run import Run, RunStatus
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.run_repository import RunRepository
from app.schemas.api_key import ApiKeyCreate
from app.services import api_key_service, openai_chat_service, run_stream
from app.services.api_key_service import ApiKeyService
from app.services.openai_chat_service import AnswerStream, Numbering, sources_markdown, sources_of

ALICE, BOB = "alice", "bob"
EVIDENCE = "0b9f3c1e-5d2a-4c1b-9a77-3e2f1d4c5b6a"
OTHER_EVIDENCE = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f"


@pytest.fixture(autouse=True)
def _peppers(monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(ApiKey))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection).where(Collection.owner_id.in_([ALICE, BOB])))
        await session.commit()


async def _key(user_id: str = ALICE, scopes: list[str] | None = None) -> str:
    context = RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False, groups=[])
    async with async_session_factory() as db:
        _row, key = await ApiKeyService(db).create(context, ApiKeyCreate(name="test", scopes=scopes or ["chat"]))
    return key


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def _collection(owner_id: str, name: str) -> uuid.UUID:
    async with async_session_factory() as db:
        collection = Collection(owner_id=owner_id, name=name)
        db.add(collection)
        await db.commit()
        return collection.id


def _agent_answers(
    monkeypatch,
    answer: str,
    deltas: list[str] | None = None,
    citations: list[dict] | None = None,
    status: str = "completed",
    started: list | None = None,
):
    """Stands for the agent: when a run starts, it writes the stream and the result the way the agent does."""

    async def script(run_id: str) -> None:
        await asyncio.sleep(0.05)
        for piece in deltas or []:
            await run_stream.publish(run_id, run_stream.DELTA, {"text": piece, "replace": False})
        async with async_session_factory() as db:
            repository = RunRepository(db)
            run = await repository.get_by_id(uuid.UUID(run_id))
            if status == "completed":
                await ConversationRepository(db).add_message(
                    run.conversation_id,
                    MessageRole.ASSISTANT,
                    answer,
                    run_id=run.id,
                    prompt_tokens=10,
                    completion_tokens=5,
                )
                await repository.set_result(run, answer, citations or [])
            else:
                run.error = "boom"
            await repository.update_status(run, RunStatus(status), None, None)
            await db.commit()
        await run_stream.publish(run_id, run_stream.STATUS, {"status": status})

    def start(run_id, user_token=None, **_kwargs):
        if started is not None:
            started.append(run_id)
        asyncio.get_running_loop().create_task(script(run_id))

    monkeypatch.setattr("app.services.run_service.agent_runner.start", start)


CITATIONS = [
    {
        "evidence_id": EVIDENCE,
        "source": "Telework policy",
        "vdb_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "page_number": 3,
        "quote": "Two days a week.",
        "content": "…",
        "url": None,
        "cited": True,
    },
]
ANSWER = f"Two days a week [{EVIDENCE}]."


async def _chat(client, key: str, **body):
    return await client.post(
        "/v1/chat/completions",
        headers=_auth(key),
        json={"model": "muffin", "messages": [{"role": "user", "content": "How many days?"}], **body},
    )


# --- who may call ---


async def test_a_call_without_a_key_is_refused_in_openai_s_format(client):
    response = await client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert response.json()["error"]["type"] == "invalid_request_error"


async def test_what_is_not_a_key_of_muffin_is_refused(client):
    assert (await client.get("/v1/models", headers=_auth("sk-other-123"))).status_code == 401
    assert (await client.get("/v1/models", headers=_auth("not-a-key"))).status_code == 401
    assert (await client.get("/v1/models", headers={"Cookie": "session=abc"})).status_code == 401


async def test_a_key_for_search_only_does_not_open_the_chat(client):
    key = await _key(scopes=["search"])

    assert (await client.get("/v1/models", headers=_auth(key))).status_code == 401


async def test_a_revoked_key_stops_working_at_once(client):
    key = await _key()
    assert (await client.get("/v1/models", headers=_auth(key))).status_code == 200
    async with async_session_factory() as db:
        row = (await db.execute(select(ApiKey))).scalar_one()
        from datetime import UTC, datetime

        row.revoked_at = datetime.now(UTC)
        await db.commit()

    assert (await client.get("/v1/models", headers=_auth(key))).status_code == 401


async def test_the_api_is_off_when_no_pepper_is_set(client, monkeypatch):
    key = await _key()
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr(""))

    response = await client.get("/v1/models", headers=_auth(key))

    assert response.status_code == 503


# --- models ---


async def test_models_are_muffin_and_the_top_level_collections_the_owner_reads(client):
    mine = await _collection(ALICE, "Droit du travail")
    await _collection(BOB, "Secret de Bob")
    key = await _key(ALICE)

    response = await client.get("/v1/models", headers=_auth(key))

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [model["id"] for model in body["data"]] == ["muffin", f"muffin:collection:{mine}"]
    assert all(model["object"] == "model" for model in body["data"])


async def test_a_model_that_does_not_exist_or_a_collection_one_cannot_read_is_not_found(client):
    theirs = await _collection(BOB, "Secret de Bob")
    key = await _key(ALICE)

    for model in ("gpt-4o", f"muffin:collection:{theirs}", "muffin:collection:not-an-id"):
        response = await _chat(client, key, model=model)
        assert response.status_code == 404, model
        assert response.json()["error"]["code"] == "model_not_found"
        assert (await client.get(f"/v1/models/{model}", headers=_auth(key))).status_code == 404


# --- a chat completion ---


async def test_a_completion_has_the_answer_with_numbered_citations_and_its_sources(client, monkeypatch):
    _agent_answers(monkeypatch, ANSWER, citations=CITATIONS)
    key = await _key()

    response = await _chat(client, key)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-") and body["model"] == "muffin"
    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop" and choice["message"]["role"] == "assistant"
    assert choice["message"]["content"].startswith("Two days a week [1].")
    assert "**Sources**" in choice["message"]["content"] and "[1] Telework policy, p. 3" in choice["message"]["content"]
    assert EVIDENCE not in choice["message"]["content"]
    assert body["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert body["sources"][0]["index"] == 1 and body["sources"][0]["name"] == "Telework policy"
    assert body["sources"][0]["excerpt"] == "Two days a week."


async def test_the_run_is_the_owner_s_limited_to_the_model_and_asks_no_question(client, monkeypatch):
    _agent_answers(monkeypatch, "Fine.")
    mine = await _collection(ALICE, "Droit du travail")
    key = await _key(ALICE)

    response = await _chat(client, key, model=f"muffin:collection:{mine}")

    assert response.status_code == 200
    async with async_session_factory() as db:
        run = (await db.execute(select(Run))).scalar_one()
    assert run.user_id == ALICE
    assert run.pinned_collection_ids == [str(mine)]
    assert run.interactive is False
    # The planner may not go on to the other collections of the owner.
    assert run.scope_locked is True


async def test_a_call_makes_a_conversation_apart_that_the_sidebar_and_search_do_not_show(client, monkeypatch):
    _agent_answers(monkeypatch, "Fine.")
    key = await _key()
    app.dependency_overrides.clear()

    await _chat(client, key)

    async with async_session_factory() as db:
        conversation = (await db.execute(select(Conversation))).scalar_one()
        listed, total = await ConversationRepository(db).list_by_owner(ALICE, limit=10, offset=0)
        hits, hits_total = await ConversationRepository(db).search_by_owner(ALICE, "days", limit=10, offset=0)
    assert conversation.source == "api" and conversation.user_id == ALICE
    assert list(listed) == [] and total == 0
    assert hits == [] and hits_total == 0


async def test_the_history_of_the_request_is_the_history_of_the_conversation(client, monkeypatch):
    _agent_answers(monkeypatch, "Fine.")
    key = await _key()

    await client.post(
        "/v1/chat/completions",
        headers=_auth(key),
        json={
            "model": "muffin",
            "messages": [
                {"role": "system", "content": "Be brief"},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": [{"type": "text", "text": "And now?"}]},
            ],
        },
    )

    async with async_session_factory() as db:
        conversation = (await db.execute(select(Conversation))).scalar_one()
        messages = await ConversationRepository(db).list_messages(conversation.id)
    assert [(row[0].role.value, row[0].content) for row in messages][:3] == [
        ("user", "Hello"),
        ("assistant", "Hi"),
        ("user", "And now?"),
    ]


async def test_the_history_of_the_request_goes_through_the_guardrails_that_need_no_model(client, monkeypatch):
    """No run checks the earlier messages a client sends along: the guardrails that run in code do (#516) - and the ones
    that would call a model are for the question, not asked once for each message of a long history."""
    from app.guardrails import llm as llm_guardrail
    from app.models.guardrail import Enforcement, Guardrail, GuardrailType

    async def forbidden(*args, **kwargs):
        raise AssertionError("a model was asked for a message of the history")

    monkeypatch.setattr(llm_guardrail, "_ask", forbidden)
    _agent_answers(monkeypatch, "Fine.")
    async with async_session_factory() as db:
        db.add_all(
            [
                Guardrail(
                    name="Masque",
                    type=GuardrailType.RULES,
                    config={"builtins": ["email"]},
                    enabled=True,
                    enforcement=Enforcement.REDACT,
                ),
                Guardrail(
                    name="Bloque",
                    type=GuardrailType.RULES,
                    config={"builtins": ["iban"]},
                    enabled=True,
                    enforcement=Enforcement.BLOCK,
                ),
                Guardrail(name="Juge", type=GuardrailType.LLM, config={}, enabled=True, enforcement=Enforcement.BLOCK),
            ]
        )
        await db.commit()
    key = await _key()

    try:
        await client.post(
            "/v1/chat/completions",
            headers=_auth(key),
            json={
                "model": "muffin",
                "messages": [
                    {"role": "user", "content": "Écrire à jean@example.fr"},
                    {"role": "assistant", "content": "D'accord"},
                    {"role": "user", "content": "Mon IBAN : FR76 3000 6000 0112 3456 7890 189"},
                    {"role": "assistant", "content": "Noté"},
                    {"role": "user", "content": "Et maintenant ?"},
                ],
            },
        )
        async with async_session_factory() as db:
            conversation = (await db.execute(select(Conversation))).scalar_one()
            rows = await ConversationRepository(db).list_messages(conversation.id)
            kept = [
                (row[0].role.value, row[0].redacted_content, row[0].guardrail_action, row[0].content) for row in rows
            ][:4]
    finally:
        async with async_session_factory() as db:
            await db.execute(delete(Guardrail))
            await db.commit()

    assert kept[0][1:3] == ("Écrire à [EMAIL]", "redacted") and kept[0][3] == "Écrire à jean@example.fr"
    assert kept[1][1:3] == (None, None)  # an answer of the assistant is not the person's text
    assert kept[2][1:3] == (None, "blocked")


async def test_a_conversation_of_muffin_can_be_gone_on_with(client, monkeypatch):
    _agent_answers(monkeypatch, "Fine.")
    async with async_session_factory() as db:
        conversation = await ConversationRepository(db).create(ALICE, title="Real")
        await db.commit()
    key = await _key(ALICE)

    response = await client.post(
        "/v1/chat/completions",
        headers={**_auth(key), "X-Muffin-Conversation": str(conversation.id)},
        json={"model": "muffin", "messages": [{"role": "user", "content": "Next?"}]},
    )

    assert response.status_code == 200
    assert response.json()["muffin"]["conversation_id"] == str(conversation.id)
    async with async_session_factory() as db:
        assert (await db.get(Conversation, conversation.id)).source is None
        assert len((await db.execute(select(Conversation))).scalars().all()) == 1


async def test_nobody_goes_on_with_a_conversation_of_someone_else(client, monkeypatch):
    _agent_answers(monkeypatch, "Fine.")
    async with async_session_factory() as db:
        conversation = await ConversationRepository(db).create(BOB, title="Bob's")
        await db.commit()
    key = await _key(ALICE)

    response = await client.post(
        "/v1/chat/completions",
        headers={**_auth(key), "X-Muffin-Conversation": str(conversation.id)},
        json={"model": "muffin", "messages": [{"role": "user", "content": "Next?"}]},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": [{"type": "function", "function": {"name": "f"}}]},
        {"functions": [{"name": "f"}]},
        {"response_format": {"type": "json_object"}},
        {"logprobs": True},
        {"n": 2},
    ],
)
async def test_what_the_agent_cannot_do_is_refused_not_ignored(client, extra):
    key = await _key()

    response = await _chat(client, key, **extra)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_parameter"


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "assistant", "content": "Hi"}],
        [{"role": "user", "content": "  "}],
        [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}],
    ],
)
async def test_a_request_without_a_question_in_text_is_refused(client, messages):
    key = await _key()

    response = await client.post(
        "/v1/chat/completions", headers=_auth(key), json={"model": "muffin", "messages": messages}
    )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


async def test_a_body_that_is_not_one_is_refused_in_openai_s_format(client):
    key = await _key()

    response = await client.post("/v1/chat/completions", headers=_auth(key), json={"model": "muffin"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_a_run_that_fails_tells_nothing_of_why(client, monkeypatch):
    _agent_answers(monkeypatch, "", status="failed")
    key = await _key()

    response = await _chat(client, key)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "run_failed"
    assert "boom" not in response.text


async def test_a_user_cannot_have_more_answers_in_the_making_than_allowed(client, monkeypatch):
    monkeypatch.setattr(openai_chat_service._settings, "OPENAI_API_RUNS_PER_USER", 1)
    openai_chat_service._in_the_making[ALICE] = 1
    key = await _key(ALICE)
    try:
        response = await _chat(client, key)
    finally:
        openai_chat_service._in_the_making.clear()

    assert response.status_code == 429
    assert response.headers["retry-after"]


async def test_an_answer_that_takes_too_long_is_cancelled(client, monkeypatch):
    monkeypatch.setattr(openai_chat_service._settings, "OPENAI_API_TIMEOUT_SECONDS", 0)
    cancelled: list = []
    monkeypatch.setattr("app.services.run_service.agent_runner.start", lambda *a, **k: None)
    monkeypatch.setattr("app.services.run_service.agent_runner.cancel", lambda run_id: cancelled.append(run_id))
    key = await _key()

    response = await _chat(client, key)

    assert response.status_code == 504
    assert len(cancelled) == 1
    async with async_session_factory() as db:
        assert (await db.execute(select(Run))).scalar_one().cancel_requested is True


async def test_conversations_made_by_the_api_are_purged_after_a_while(client, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import update

    _agent_answers(monkeypatch, "Fine.")
    key = await _key()
    await _chat(client, key)
    async with async_session_factory() as db:
        await db.execute(update(Conversation).values(updated_at=Conversation.updated_at - timedelta(days=30)))
        await db.commit()

    await _chat(client, key)

    async with async_session_factory() as db:
        assert len((await db.execute(select(Conversation))).scalars().all()) == 1


# --- streaming ---


def _events(text: str) -> list[str]:
    return [line.removeprefix("data: ") for line in text.split("\n\n") if line.startswith("data: ")]


async def test_a_stream_gives_the_same_text_as_the_completion_then_done(client, monkeypatch):
    # The marker is cut in two between two pieces, as the model's tokens may cut it.
    deltas = ["Two days a ", "week [0b9f3c1e-5d2a-", "4c1b-9a77-3e2f1d4c5b6a", "]."]
    _agent_answers(monkeypatch, ANSWER, deltas=deltas, citations=CITATIONS)
    key = await _key()

    response = await _chat(client, key, stream=True, stream_options={"include_usage": True})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events[-1] == "[DONE]"
    chunks = [json.loads(event) for event in events[:-1]]
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    text = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks if chunk["choices"])
    assert text.startswith("Two days a week [1].")
    assert "[1] Telework policy, p. 3" in text and EVIDENCE not in text and "[0b9f" not in text
    finish = [chunk for chunk in chunks if chunk["choices"] and chunk["choices"][0]["finish_reason"]]
    assert finish[0]["choices"][0]["finish_reason"] == "stop" and finish[0]["sources"][0]["index"] == 1
    assert chunks[-1]["choices"] == [] and chunks[-1]["usage"]["total_tokens"] == 15


async def test_a_stream_of_an_answer_that_was_not_streamed_still_gives_it(client, monkeypatch):
    _agent_answers(monkeypatch, "Nothing found.")
    key = await _key()

    response = await _chat(client, key, stream=True)

    text = "".join(json.loads(event)["choices"][0]["delta"].get("content", "") for event in _events(response.text)[:-1])
    assert text == "Nothing found."


async def test_the_steps_are_in_the_stream_only_when_asked_and_apart_from_the_text(client, monkeypatch):
    async def script(run_id: str) -> None:
        await asyncio.sleep(0.05)
        await run_stream.publish(
            run_id, run_stream.STATUS, {"status": "running", "current_activity": "Searching the collections"}
        )
        await _agent_answers_finish(run_id)

    async def _agent_answers_finish(run_id: str) -> None:
        async with async_session_factory() as db:
            repository = RunRepository(db)
            run = await repository.get_by_id(uuid.UUID(run_id))
            await ConversationRepository(db).add_message(
                run.conversation_id, MessageRole.ASSISTANT, "Done.", run_id=run.id
            )
            await repository.set_result(run, "Done.", [])
            await repository.update_status(run, RunStatus.COMPLETED, None, None)
            await db.commit()
        await run_stream.publish(run_id, run_stream.STATUS, {"status": "completed"})

    monkeypatch.setattr(
        "app.services.run_service.agent_runner.start",
        lambda run_id, *a, **k: asyncio.get_running_loop().create_task(script(run_id)),
    )
    key = await _key()

    quiet = await _chat(client, key, stream=True)
    with_steps = await _chat(client, key, stream=True, muffin={"steps": True})

    assert "reasoning_content" not in quiet.text
    deltas = [json.loads(event)["choices"][0]["delta"] for event in _events(with_steps.text)[:-1]]
    assert [delta["reasoning_content"] for delta in deltas if "reasoning_content" in delta] == [
        "Searching the collections\n"
    ]
    assert "".join(delta.get("content", "") for delta in deltas) == "Done."


# --- the openai SDK, as a client uses it ---


async def test_the_openai_sdk_works_with_the_base_url_alone(client, monkeypatch):
    from openai import AsyncOpenAI

    _agent_answers(monkeypatch, ANSWER, deltas=["Two days a week [", f"{EVIDENCE}]."], citations=CITATIONS)
    key = await _key()
    sdk = AsyncOpenAI(base_url="http://test/v1", api_key=key, http_client=client)
    messages = [{"role": "user", "content": "How many days?"}]

    models = await sdk.models.list()
    completion = await sdk.chat.completions.create(model="muffin", messages=messages)
    streamed = await sdk.chat.completions.create(
        model="muffin", messages=messages, stream=True, stream_options={"include_usage": True}
    )
    pieces, usage = [], None
    async for chunk in streamed:
        if chunk.choices:
            pieces.append(chunk.choices[0].delta.content or "")
        if chunk.usage:
            usage = chunk.usage

    assert [model.id for model in models.data] == ["muffin"]
    assert completion.choices[0].message.content.startswith("Two days a week [1].")
    assert completion.usage.total_tokens == 15
    assert "".join(pieces).startswith("Two days a week [1].")
    assert usage.total_tokens == 15


# --- the pieces ---


def test_a_marker_cut_between_two_pieces_is_held_back_until_it_is_whole():
    numbering = Numbering()
    stream = AnswerStream(numbering)

    pieces = [
        stream.add("See [0b9f3c1e-5d2a", replace=False),
        stream.add(f"-4c1b-9a77-3e2f1d4c5b6a] and [{OTHER_EVIDENCE}][", replace=False),
        stream.add("not a marker", replace=False),
    ]

    # An opening bracket that nothing closes is held back too, and said at the end if it was not a marker.
    assert pieces == ["See ", "[1] and [2]", ""]
    assert numbering.numbers == {EVIDENCE: 1, OTHER_EVIDENCE: 2}


def test_the_end_adds_only_what_the_stream_did_not_say():
    stream = AnswerStream(Numbering())
    first = stream.add("Hello [x", replace=False)

    rest = stream.finish("Hello [x] there")

    assert (first, rest) == ("Hello ", "[x] there")


def test_a_final_answer_that_is_not_the_streamed_one_adds_nothing():
    stream = AnswerStream(Numbering())
    stream.add("Hello world", replace=False)

    assert stream.finish("Something else entirely") == ""


def test_one_source_is_listed_once_by_the_number_it_was_cited_with():
    numbering = Numbering()
    text = numbering.convert(f"A [{EVIDENCE}] B [{OTHER_EVIDENCE}, {EVIDENCE}]")

    sources = sources_of(numbering, [{"evidence_id": EVIDENCE, "source": "One", "url": "https://x/1"}])

    assert text == "A [1] B [2][1]"
    assert [(source["index"], source["name"]) for source in sources] == [(1, "One"), (2, None)]
    assert sources_markdown([]) == ""
    assert "[1] One - https://x/1" in sources_markdown(sources)
