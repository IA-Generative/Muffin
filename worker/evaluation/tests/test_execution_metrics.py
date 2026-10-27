import threading
import time
from types import SimpleNamespace

import pytest

import app.execution_metrics as execution_metrics


@pytest.fixture
def sent(monkeypatch) -> list[dict]:
    # What other tests left in the sender's queue goes out before this one starts listening.
    execution_metrics._sender.flush()
    metrics: list[dict] = []
    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", metrics.append)
    return metrics


def _spin(seconds: float) -> None:
    end = time.thread_time() + seconds
    while time.thread_time() < end:
        pass


def _task(name: str = "app.tasks.run_agent") -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_a_task_reports_its_time_cpu_and_memory(sent):
    execution_metrics._start_task(task_id="t1")
    _spin(0.05)
    execution_metrics._end_task(task=_task())
    execution_metrics._sender.flush()

    assert len(sent) == 1
    metric = sent[0]
    assert (metric["kind"], metric["step"]) == ("task", "run_agent")
    assert metric["duration_seconds"] >= 0.05
    assert metric["cpu_seconds"] >= 0.04
    assert metric["peak_rss_bytes"] > 0


def test_tasks_sharing_a_process_split_its_memory_and_count_their_own_cpu(sent, monkeypatch):
    monkeypatch.setattr(execution_metrics, "_rss_bytes", lambda: 1000)
    both_running, a_may_end = threading.Event(), threading.Event()

    def task_a() -> None:  # a pool of threads: another task starts while this one runs
        execution_metrics._start_task(task_id="a")
        both_running.wait(5)
        _spin(0.02)
        a_may_end.wait(5)
        execution_metrics._end_task(task=_task("app.tasks.a"))

    thread = threading.Thread(target=task_a)
    thread.start()
    time.sleep(0.05)
    execution_metrics._start_task(task_id="b")
    both_running.set()
    execution_metrics._end_task(task=_task("app.tasks.b"))
    a_may_end.set()
    thread.join()
    execution_metrics._sender.flush()

    assert sorted((metric["step"], metric["peak_rss_bytes"]) for metric in sent) == [("a", 500), ("b", 500)]
    task_a_metric = next(metric for metric in sent if metric["step"] == "a")
    assert task_a_metric["cpu_seconds"] < 0.2  # its own thread's, not the whole process's


def test_a_task_that_never_started_reports_nothing(sent):
    execution_metrics._end_task(task=_task())
    execution_metrics._sender.flush()

    assert sent == []


def test_a_backend_that_fails_never_fails_the_task(monkeypatch):
    def refuse(_metric):
        raise RuntimeError("backend down")

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", refuse)

    execution_metrics._start_task(task_id="t1")
    execution_metrics._end_task(task=_task())
    execution_metrics._sender.flush()
