from bisect import bisect
from unittest.mock import MagicMock

from kombu.transport import redis as redis_transport

from app import task_logging, tasks
from app.config import settings as worker_settings
from app.task_revocation import TaskRevoked
from app.tasks import _shared
from app.tasks import extract as extract_tasks
from app.tasks import qa as qa_tasks
from app.windows import sliding_windows

# The list of the Redis broker a message of this priority lands in - what KEDA must watch (helm/values).
_SEP = redis_transport.Channel.sep


def test_the_priority_of_the_windows_is_a_step_of_the_redis_transport_with_a_list_of_its_own():
    steps = redis_transport.Channel.priority_steps

    assert steps[bisect(steps, _shared.WINDOW_PRIORITY) - 1] == _shared.WINDOW_PRIORITY
    assert 0 < _shared.WINDOW_PRIORITY < 9  # below the default, above the ZIP imports (BULK_PRIORITY)


def test_the_list_keda_watches_for_the_windows_is_the_one_they_are_sent_to():
    queue = "document_enrichment"
    list_name = f"{queue}{_SEP}{_shared.WINDOW_PRIORITY}"

    assert list_name == "document_enrichment\x06\x163"


def test_spawn_sends_the_task_with_the_priority_only_when_one_is_given(monkeypatch):
    monkeypatch.setattr(_shared, "backend_client", MagicMock())
    task = MagicMock()

    _shared._spawn(task, ["doc"], "app.tasks.x", "doc", "parent")
    task.apply_async.assert_called_with(args=["doc"])

    _shared._spawn(task, ["doc"], "app.tasks.x", "doc", "parent", priority=3)
    task.apply_async.assert_called_with(args=["doc"], priority=3)


def test_a_document_sends_its_windows_below_the_tasks_that_make_it_searchable(monkeypatch):
    backend = MagicMock()
    backend.get_collection_settings.return_value = {
        "chunking_strategy": "paragraph",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "embedder",
        "instructions": {},
        "generation_models": {},
        "pipeline_windows": {},
    }
    backend.get_pages.return_value = [{"page_number": n, "content": f"Page {n}."} for n in range(1, 9)]
    backend.get_document.return_value = {"content_hash": None}
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(_shared, "_spawn", MagicMock())

    tasks.chunk_document("doc-1", "col-1")

    by_task = {}
    for call in _shared._spawn.call_args_list:
        by_task.setdefault(call.args[2], []).append(call.kwargs.get("priority"))
    assert by_task["app.tasks.summarize_document"] == [None]
    # 7 windows of QA, 5 of entities: only the first lanes are sent, the rest follows as they end.
    assert len(by_task["app.tasks.generate_qa_window"]) == worker_settings.ENRICHMENT_WINDOW
    assert set(by_task["app.tasks.generate_qa_window"]) == {_shared.WINDOW_PRIORITY}
    assert len(by_task["app.tasks.extract_entities_window"]) == worker_settings.ENRICHMENT_WINDOW
    assert set(by_task["app.tasks.extract_entities_window"]) == {_shared.WINDOW_PRIORITY}


# -- lanes: a document sends a few windows at a time, each one ending sends the next of its lane ----------


def _run_lanes(monkeypatch, pages, size, slide, step, *, fail_on=None, runs=None):
    """Starts the lanes of a document and runs every task sent, one at a time, as a worker would: returns what
    was run, in order, and the most that was waiting to be run at once."""
    monkeypatch.setattr(worker_settings, "ENRICHMENT_WINDOW", step)
    monkeypatch.setattr(_shared, "backend_client", MagicMock())
    waiting, executed = [], []
    monkeypatch.setattr(
        _shared,
        "_spawn",
        lambda task, args, name, document_id, parent, priority=None: waiting.append((args, priority)),
    )

    def window(document_id, collection_id, start, end, k):
        executed.append((start, end))
        if (start, end) == fail_on:
            raise RuntimeError("the model failed on this window")

    monkeypatch.setattr(qa_tasks, "_generate_qa_window", window)
    windows = sliding_windows(pages, size, slide)
    _shared.start_lanes(
        qa_tasks.generate_qa_window,
        "app.tasks.generate_qa_window",
        "doc",
        "col",
        windows,
        (pages, size, slide),
        [3],
        "p",
    )
    most_waiting = len(waiting)
    while waiting:
        args, priority = waiting.pop(0)
        assert priority == _shared.WINDOW_PRIORITY
        try:
            qa_tasks.generate_qa_window(*args)
        except RuntimeError:
            pass
        most_waiting = max(most_waiting, len(waiting))
    return executed, windows, most_waiting


def test_every_window_is_run_once_whatever_the_number_of_lanes(monkeypatch):
    for pages, size, slide, step in [
        (40, 2, 1, 4),
        (3, 2, 1, 4),
        (1, 2, 1, 4),
        (25, 4, 2, 3),
        (10, 2, 1, 1),
        (7, 2, 1, 50),
    ]:
        executed, windows, _ = _run_lanes(monkeypatch, pages, size, slide, step)

        assert sorted(executed) == windows, (pages, size, slide, step)


def test_a_document_never_has_more_windows_waiting_than_its_lanes(monkeypatch):
    _, windows, most_waiting = _run_lanes(monkeypatch, 900, 2, 1, 4)

    assert len(windows) == 899
    assert most_waiting == 4


def test_a_window_that_fails_does_not_leave_the_rest_of_its_lane_unsent(monkeypatch):
    executed, windows, _ = _run_lanes(monkeypatch, 20, 2, 1, 4, fail_on=(1, 2))

    assert sorted(executed) == windows


def test_a_task_that_was_stopped_sends_nothing_more(monkeypatch):
    sent = []
    monkeypatch.setattr(_shared, "_spawn", lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(qa_tasks, "_generate_qa_window", MagicMock())

    def revoked():
        raise TaskRevoked()

    monkeypatch.setattr(_shared, "raise_if_revoked", revoked)
    lane = {"index": 0, "step": 4, "pages": 40, "size": 2, "slide": 1, "parent": "p"}

    qa_tasks.generate_qa_window("doc", "col", 1, 2, 3, lane)

    assert sent == []


def test_a_window_with_no_lane_sends_nothing(monkeypatch):
    monkeypatch.setattr(_shared, "_spawn", MagicMock())
    monkeypatch.setattr(qa_tasks, "_generate_qa_window", MagicMock())

    qa_tasks.generate_qa_window("doc", "col", 1, 2, 3)

    _shared._spawn.assert_not_called()


def test_the_entity_windows_follow_their_lane_too(monkeypatch):
    monkeypatch.setattr(extract_tasks, "_extract_entities_window", MagicMock())
    sent = []
    monkeypatch.setattr(_shared, "_spawn", lambda task, args, *rest, **kwargs: sent.append(args))
    lane = {"index": 1, "step": 4, "pages": 40, "size": 4, "slide": 1, "parent": "p"}

    extract_tasks.extract_entities_window("doc", "col", 2, 5, lane)

    assert sent == [["doc", "col", 6, 9, {**lane, "index": 5}]]
