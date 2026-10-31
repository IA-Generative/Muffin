"""The agent reaches the backend's own routes in process, through the same key as any worker."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.agent.backend_client import BackendClient
from app.agent.runner import AgentRunner
from app.core.security import worker_auth
from app.db import async_session_factory
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run, RunStatus

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
async def _runtime(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    yield
    async with async_session_factory() as session:
        await session.execute(Run.__table__.delete())
        await session.execute(Conversation.__table__.delete())
        await session.commit()


async def _run(status: RunStatus = RunStatus.QUEUED, updated: datetime | None = None) -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id="dev-user", title="t")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Bonjour")
        session.add(message)
        await session.flush()
        run = Run(user_id="dev-user", message_id=message.id, conversation_id=conversation.id, query="Bonjour")
        run.status = status
        session.add(run)
        await session.commit()
        if updated is not None:
            await session.execute(update(Run).where(Run.id == run.id).values(updated_at=updated))
            await session.commit()
        return run.id


def _client() -> BackendClient:
    client = BackendClient()
    client._api_key = API_KEY
    client._http = None
    return client


async def test_the_agent_reads_the_run_through_the_backends_own_route():
    run_id = await _run()

    run = await _client().get_run(str(run_id))

    assert run["query"] == "Bonjour" and run["cancel_requested"] is False


async def test_the_agent_writes_through_the_backends_own_routes():
    run_id = await _run()

    await _client().update_run_status(str(run_id), "running", "plan", "Analyzing your question")

    async with async_session_factory() as session:
        run = await session.get(Run, run_id)
    assert (run.status, run.current_node) == (RunStatus.RUNNING, "plan")


async def test_without_the_workers_key_the_agent_is_refused_like_any_caller():
    run_id = await _run()
    client = _client()
    client._api_key = "wrong"

    with pytest.raises(Exception, match="401"):
        await client.get_run(str(run_id))


async def test_a_run_that_stopped_progressing_is_failed_and_a_live_one_is_left_alone():
    stale = await _run(RunStatus.RUNNING, datetime.now(UTC) - timedelta(minutes=30))
    live = await _run(RunStatus.RUNNING)
    done = await _run(RunStatus.COMPLETED, datetime.now(UTC) - timedelta(days=2))

    failed = await AgentRunner().fail_stale()

    async with async_session_factory() as session:
        assert failed == 1
        assert (await session.get(Run, stale)).status == RunStatus.FAILED
        assert "interrompue" in (await session.get(Run, stale)).error
        assert (await session.get(Run, live)).status == RunStatus.RUNNING
        assert (await session.get(Run, done)).status == RunStatus.COMPLETED


class _Chunk:
    def __init__(self, text: str | None = None, usage=None) -> None:
        delta = type("Delta", (), {"content": text})()
        self.choices = [type("Choice", (), {"delta": delta})()] if text is not None else []
        self.usage = usage


class _Completions:
    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate

    async def create(self, **kwargs):
        async def chunks():
            yield _Chunk("Vingt-cinq ")
            await self.gate.wait()  # the model is still writing: nothing after this until the test says so
            yield _Chunk("jours.")
            yield _Chunk(usage=type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 5})())

        return chunks()


async def test_the_answer_reaches_the_agent_as_the_model_writes_it_not_when_it_is_done(monkeypatch):
    from app.routers import internal_llm

    gate = asyncio.Event()
    fake = type("Client", (), {"chat": type("Chat", (), {"completions": _Completions(gate)})()})()
    monkeypatch.setattr(internal_llm, "_openai_client", fake)
    stream = _client().llm_chat_stream("m", [{"role": "user", "content": "Combien ?"}])

    first = await asyncio.wait_for(anext(stream), 5)  # arrives while the model has not finished

    assert first == {"delta": "Vingt-cinq "}
    gate.set()
    rest = [item async for item in stream]
    assert rest[0] == {"delta": "jours."} and rest[-1]["done"] is True
    assert (rest[-1]["prompt_tokens"], rest[-1]["completion_tokens"]) == (10, 5)
