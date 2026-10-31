"""What a run and its steps cost the machine, recorded without ever failing or delaying the run."""

import app.agent.execution_metrics as execution_metrics
from app.agent.usage_context import set_usage, start_run


def test_a_step_is_reported_with_whose_consumption_it_is(monkeypatch):
    sent = []
    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", sent.append)
    start_run("run-1", "user-1")
    set_usage(step="plan")

    execution_metrics.report("node", "plan", 1.5, 0.25, None)
    execution_metrics._sender.flush()

    [metric] = sent
    assert metric["kind"] == "node" and metric["step"] == "plan"
    assert metric["duration_seconds"] == 1.5 and metric["cpu_seconds"] == 0.25
    assert metric["run_id"] == "run-1" and metric["user_id"] == "user-1"


def test_a_negative_duration_is_never_reported(monkeypatch):
    sent = []
    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", sent.append)

    execution_metrics.report("node", "gate", -1.0, -1.0, None)
    execution_metrics._sender.flush()

    assert sent[-1]["duration_seconds"] == 0.0 and sent[-1]["cpu_seconds"] == 0.0


def test_the_run_as_a_whole_is_reported_when_it_ends_even_if_it_fails(monkeypatch):
    sent = []
    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", sent.append)
    start_run("run-2", "user-1")

    try:
        with execution_metrics.measured_run():
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    [metric] = [m for m in sent if m["run_id"] == "run-2"]
    assert metric["kind"] == "task" and metric["step"] == "run_agent" and metric["peak_rss_bytes"]


def test_a_metric_that_cannot_be_sent_is_dropped_not_raised(monkeypatch):
    def refuse(metric):
        raise ConnectionError("down")

    monkeypatch.setattr(execution_metrics.backend_client, "add_execution_metric", refuse)

    execution_metrics.report("node", "gate", 1.0, 1.0, None)
    execution_metrics._sender.flush()  # must not raise
