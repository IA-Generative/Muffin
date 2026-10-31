"""A run is a background task of the backend: it starts at once, carries the user's token and nothing else of them, and
stops cleanly."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.agent import runner as runner_module
from app.agent.cancellation import RunCancelled, raise_if_cancelled
from app.agent.runner import AgentRunner
from app.agent.usage_context import current_usage
from app.agent.user_token import current_user_token


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.release = threading.Event()
        self.started = threading.Event()
        self.block = False
        self.error: Exception | None = None

    def _record(self, kind: str, run_id: str, answer: str | None = None) -> None:
        self.calls.append(
            {
                "kind": kind,
                "run_id": run_id,
                "answer": answer,
                "token": current_user_token(),
                "usage": current_usage(),
                "thread": threading.current_thread(),
            }
        )
        self.started.set()
        if self.block:
            self.release.wait(5)
        if self.error:
            raise self.error

    def run(self, run_id: str) -> None:
        self._record("run", run_id)

    def resume(self, run_id: str, answer: str) -> None:
        self._record("resume", run_id, answer)


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(runner_module, "agent_service", fake)
    monkeypatch.setattr(runner_module, "measured_run", lambda: __import__("contextlib").nullcontext())
    return fake


@pytest.fixture
async def runner():
    instance = AgentRunner()
    yield instance
    for task in list(instance._tasks.values()):
        task.cancel()
    if instance._executor is not None:
        instance._executor.shutdown(wait=False, cancel_futures=True)


async def _finished(runner: AgentRunner) -> None:
    while runner._tasks:
        await asyncio.sleep(0.01)


async def test_a_run_starts_in_the_background_and_start_returns_at_once(service, runner):
    service.block = True

    runner.start("run-1", "token-1")

    assert runner.is_running("run-1")
    await asyncio.to_thread(service.started.wait, 5)
    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)
    assert [c["run_id"] for c in service.calls] == ["run-1"]


async def test_the_run_never_executes_in_the_thread_of_the_loop(service, runner):
    runner.start("run-1", None)
    await asyncio.wait_for(_finished(runner), 5)

    assert service.calls[0]["thread"] is not threading.main_thread()


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
    assert current_user_token() is None  # nor does the loop that started them


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
    runner._executor = None
    runner.start("run-1", None)
    runner.start("run-2", None)

    await asyncio.to_thread(service.started.wait, 5)
    await asyncio.sleep(0.1)
    assert [c["run_id"] for c in service.calls] == ["run-1"]  # the second one has not begun

    service.release.set()
    await asyncio.wait_for(_finished(runner), 5)
    assert [c["run_id"] for c in service.calls] == ["run-1", "run-2"]


async def test_a_cancelled_run_stops_what_waits_at_its_next_look(runner):
    from app.agent.usage_context import start_run

    def waiting() -> str:
        start_run("run-9")
        raise_if_cancelled()  # fine until it is cancelled
        runner.cancel("run-9")
        try:
            raise_if_cancelled()
        except RunCancelled:
            return "stopped"
        return "went on"

    assert await asyncio.to_thread(waiting) == "stopped"


async def test_the_cancellation_of_one_run_does_not_touch_another(runner):
    from app.agent.usage_context import start_run

    def other() -> str:
        start_run("run-other")
        raise_if_cancelled()
        return "fine"

    runner.cancel("run-9")

    assert await asyncio.to_thread(other) == "fine"


def test_a_run_that_stopped_progressing_is_a_run_nobody_runs_any_more():
    assert runner_module.STALE_AFTER >= timedelta(minutes=5)
    assert datetime.now(UTC) - runner_module.STALE_AFTER < datetime.now(UTC)
