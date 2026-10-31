"""What a run and its steps cost, recorded without ever failing or delaying the run."""

import asyncio

import app.agent.execution_metrics as execution_metrics
from app.agent.usage_context import set_usage, start_run


async def test_a_step_is_reported_with_whose_consumption_it_is(monkeypatch):
    sent = []

    async def record(metric):
        sent.append(metric)

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", record)
    start_run("run-1", "user-1")
    set_usage(step="plan")

    execution_metrics.report("node", "plan", 1.5)
    await execution_metrics.flush()

    [metric] = sent
    assert metric["kind"] == "node" and metric["step"] == "plan"
    assert metric["duration_seconds"] == 1.5 and metric["cpu_seconds"] == 0.0
    assert metric["run_id"] == "run-1" and metric["user_id"] == "user-1"


async def test_a_negative_duration_is_never_reported(monkeypatch):
    sent = []

    async def record(metric):
        sent.append(metric)

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", record)

    execution_metrics.report("node", "gate", -1.0)
    await execution_metrics.flush()

    assert sent[-1]["duration_seconds"] == 0.0


async def test_the_run_as_a_whole_is_reported_when_it_ends_even_if_it_fails(monkeypatch):
    sent = []

    async def record(metric):
        sent.append(metric)

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", record)
    start_run("run-2", "user-1")

    try:
        async with execution_metrics.measured_run():
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    [metric] = [m for m in sent if m["run_id"] == "run-2"]
    assert metric["kind"] == "task" and metric["step"] == "run_agent" and metric["peak_rss_bytes"]


async def test_a_metric_that_cannot_be_sent_is_dropped_not_raised(monkeypatch):
    async def refuse(metric):
        raise ConnectionError("down")

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", refuse)

    execution_metrics.report("node", "gate", 1.0)
    await execution_metrics.flush()  # must not raise


async def test_a_backend_that_does_not_answer_never_piles_up_tasks(monkeypatch):
    gate = asyncio.Event()

    async def hang(metric):
        await gate.wait()

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", hang)
    monkeypatch.setattr(execution_metrics, "MAX_IN_FLIGHT", 3)

    for _ in range(10):
        execution_metrics.report("node", "gate", 1.0)

    assert len(execution_metrics._pending) <= 3
    gate.set()
    await execution_metrics.flush()
