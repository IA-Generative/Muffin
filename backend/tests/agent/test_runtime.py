"""The agent runs in a thread of the backend and reaches the backend's loop from there."""

import asyncio
import threading

import pytest

from app.agent import runtime


@pytest.fixture(autouse=True)
async def _bound_loop():
    runtime.bind_loop(asyncio.get_running_loop())


async def test_a_coroutine_is_run_on_the_backends_loop_from_a_thread_of_a_run():
    seen = {}

    async def where() -> str:
        seen["loop_thread"] = threading.current_thread()
        return "done"

    result = await asyncio.to_thread(runtime.run_on_loop, where())

    assert result == "done"
    assert seen["loop_thread"] is threading.main_thread()


async def test_what_an_async_generator_yields_comes_one_item_at_a_time_to_the_thread():
    async def lines():
        for index in range(3):
            yield f"line {index}"
            await asyncio.sleep(0)

    collected = await asyncio.to_thread(lambda: list(runtime.iterate_on_loop(lines())))

    assert collected == ["line 0", "line 1", "line 2"]


async def test_an_error_of_the_loop_side_reaches_the_thread():
    async def boom():
        raise ValueError("no model")

    with pytest.raises(ValueError, match="no model"):
        await asyncio.to_thread(runtime.run_on_loop, boom())


def test_without_a_loop_the_runtime_says_so_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(runtime, "_loop", None)

    async def never():
        return 1

    with pytest.raises(RuntimeError, match="not started"):
        runtime.run_on_loop(never())
