from bisect import bisect
from unittest.mock import MagicMock

from kombu.transport import redis as redis_transport

from app import task_logging, tasks
from app.tasks import _shared

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
    assert len(by_task["app.tasks.generate_qa_window"]) > 1
    assert set(by_task["app.tasks.generate_qa_window"]) == {_shared.WINDOW_PRIORITY}
    assert len(by_task["app.tasks.extract_entities_window"]) > 1
    assert set(by_task["app.tasks.extract_entities_window"]) == {_shared.WINDOW_PRIORITY}
