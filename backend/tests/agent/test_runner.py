"""A run is a background task of the backend: it starts at once, carries the user's token and nothing else of them, and
stops cleanly."""

import asyncio
import contextlib

import pytest

from app.agent import runner as runner_module
from app.agent.cancellation import RunCancelled, raise_if_cancelled
from app.agent.runner import AgentRunner
from app.agent.usage_context import current_usage, start_run
from app.agent.user_token import current_user_token


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.block = False
        self.error: Exception | None = None

    async def _record(self, kind: str, run_id: str, answer: str | None = None) -> None:
        self.calls.append(
            {
                "kind": kind,
                "run_id": run_id,
                "answer": answer,
                "token": current_user_token(),
                "usage": current_usage(),
            }
        )
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.error:
            raise self.error

    async def run(self, run_id: str) -> None:
        await self._record("run", run_id)

    async def resume(self, run_id: str, answer: str) -> None:
        await self._record("resume", run_id, answer)


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(runner_module, "agent_service", fake)

    @contextlib.asynccontextmanager
    async def not_measured():
        yield

    monkeypatch.setattr(runner_module, "measured_run", not_measured)
    return fake


@pytest.fixture
async def runner():
    instance = AgentRunner()
    yield instance
    for task in list(instance._tasks.values()):
        task.cancel()
    await asyncio.gather(*instance._tasks.values(), return_exceptions=True)


async def _finished(runner: AgentRunner) -> None:
    while runner._tasks:
        await asyncio.sleep(0.01)


async def test_a_run_starts_in_the_background_and_start_returns_at_once(service, runner):
    service.block = True

    runner.start("run-1", "token-1")

    assert runner.is_running("run-1")
    await asyncio.wait_for(service.started.wait(), 5)
    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)
    assert [c["run_id"] for c in service.calls] == ["run-1"]


async def test_two_runs_share_the_loop_without_one_waiting_for_the_other(service, runner):
    service.block = True

    runner.start("run-1", None)
    runner.start("run-2", None)
    for _ in range(100):
        if len(service.calls) == 2:
            break
        await asyncio.sleep(0.01)

    assert [c["run_id"] for c in service.calls] == ["run-1", "run-2"]  # both began; neither had finished
    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)


async def test_the_users_token_and_the_run_are_what_the_run_sees_of_its_context(service, runner):
    runner.start("run-1", "the-users-token")
    await asyncio.wait_for(_finished(runner), 5)

    [call] = service.calls
    assert call["token"] == "the-users-token"
    assert call["usage"]["run_id"] == "run-1" and call["usage"]["step"] == "run_agent"


async def test_a_run_started_later_does_not_inherit_the_token_of_another(service, runner):
    runner.start("run-1", "token-of-the-first")
    await asyncio.wait_for(_finished(runner), 5)
    runner.start("run-2", None)
    await asyncio.wait_for(_finished(runner), 5)

    assert [c["token"] for c in service.calls] == ["token-of-the-first", None]
    assert current_user_token() is None  # nor does whoever started them


async def test_a_resumed_run_runs_the_resume_with_the_answer(service, runner):
    runner.start("run-1", "t", resume_answer="HR")
    await asyncio.wait_for(_finished(runner), 5)

    assert service.calls[0]["kind"] == "resume" and service.calls[0]["answer"] == "HR"


async def test_a_run_that_raises_is_traced_and_forgotten_not_left_in_the_registry(service, runner):
    service.error = RuntimeError("model down")

    runner.start("run-1", None)
    await asyncio.wait_for(_finished(runner), 5)

    assert not runner.is_running("run-1")


async def test_the_runs_of_a_pod_are_bounded_the_others_wait_their_turn(service, runner, monkeypatch):
    monkeypatch.setattr(runner_module.settings, "MAX_CONCURRENT_RUNS", 1)
    service.block = True
    runner.start("run-1", None)
    runner.start("run-2", None)

    await asyncio.wait_for(service.started.wait(), 5)
    await asyncio.sleep(0.1)
    assert [c["run_id"] for c in service.calls] == ["run-1"]  # the second one has not begun

    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)
    assert [c["run_id"] for c in service.calls] == ["run-1", "run-2"]


async def test_cancelling_a_run_stops_what_it_is_awaiting_at_once(service, runner):
    service.block = True
    runner.start("run-1", None)
    await asyncio.wait_for(service.started.wait(), 5)

    runner.cancel("run-1")
    await asyncio.wait_for(_finished(runner), 5)

    assert not runner.is_running("run-1")  # the wait was interrupted: nobody released it


async def test_cancelling_one_run_leaves_another_alone(service, runner):
    service.block = True
    runner.start("run-1", None)
    runner.start("run-2", None)
    for _ in range(100):
        if len(service.calls) == 2:
            break
        await asyncio.sleep(0.01)

    runner.cancel("run-1")
    await asyncio.sleep(0.05)

    assert not runner.is_running("run-1") and runner.is_running("run-2")
    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)


async def test_a_cancelled_run_stops_what_waits_at_its_next_look(runner):
    async def waiting() -> str:
        start_run("run-9")
        raise_if_cancelled()  # fine until it is cancelled
        runner.cancel("run-9")
        try:
            raise_if_cancelled()
        except RunCancelled:
            return "stopped"
        return "went on"

    assert await asyncio.create_task(waiting()) == "stopped"


async def test_the_cancellation_of_one_run_does_not_touch_another(runner):
    async def other() -> str:
        start_run("run-other")
        raise_if_cancelled()
        return "fine"

    runner.cancel("run-9")

    assert await asyncio.create_task(other()) == "fine"
