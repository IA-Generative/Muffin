from contextvars import copy_context
from types import SimpleNamespace

from app import usage_context


def _task(name: str, run):
    return SimpleNamespace(name=name, run=run)


def _started(task, args=(), kwargs=None) -> dict | None:
    def start():
        usage_context._start_task(task=task, args=args, kwargs=kwargs or {})
        return usage_context.current_usage()

    return copy_context().run(start)


def test_a_task_starts_with_its_name_as_step_and_its_ids():
    def chunk_document(document_id: str, collection_id: str, strategy: str) -> None: ...

    usage = _started(_task("app.tasks.chunk_document", chunk_document), ("doc-1",), {"collection_id": "col-1"})

    assert usage == {"step": "chunk_document", "document_id": "doc-1", "collection_id": "col-1"}


def test_ids_are_also_read_from_a_payload_dict():
    def edit_document(payload: dict) -> None: ...

    usage = _started(
        _task("app.tasks.edit_document", edit_document), ({"user_id": "u-1", "document_id": "doc-1", "x": 1},)
    )

    assert usage == {"step": "edit_document", "user_id": "u-1", "document_id": "doc-1"}


def test_set_usage_narrows_the_current_context():
    def run_agent(run_id: str) -> None: ...

    def start_then_narrow():
        usage_context._start_task(task=_task("app.tasks.run_agent", run_agent), args=("run-1",))
        usage_context.set_usage(step="generate_answer", document_id=None)
        return usage_context.current_usage()

    assert copy_context().run(start_then_narrow) == {"step": "generate_answer", "run_id": "run-1"}


def test_llm_calls_carry_the_current_context(monkeypatch):
    from app.backend_client import backend_client

    sent = {}

    def post(path, json):
        sent.update(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"content": "ok"})

    monkeypatch.setattr(backend_client._client, "post", post)

    def call():
        usage_context.set_usage(step="summarize_document", document_id="doc-1")
        return backend_client.llm_chat("gpt-4o", [])

    copy_context().run(call)

    assert sent["usage"] == {"step": "summarize_document", "document_id": "doc-1"}
