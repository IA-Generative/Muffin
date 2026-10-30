from unittest.mock import MagicMock

import pytest
from qdrant_client import models

from app import tasks
from app.owui_client import OwuiFile, OwuiUser
from app.owui_vectors import OwuiChunk, OwuiVectors


def _point(point_id: str, text: str, start_index=None) -> models.Record:
    metadata = {"file_id": "f1"} | ({"start_index": start_index} if start_index is not None else {})
    return models.Record(id=point_id, payload={"text": text, "metadata": metadata})


def test_the_chunks_of_a_file_are_read_in_the_order_of_the_file():
    qdrant = MagicMock()
    qdrant.scroll.side_effect = [
        ([_point("b", "second", 120), _point("a", "first", 0)], "next"),
        ([_point("c", "third", 300)], None),
    ]

    chunks = OwuiVectors(qdrant, prefix="open-webui").chunks("kb1", "f1")

    assert chunks == [OwuiChunk("a", "first"), OwuiChunk("b", "second"), OwuiChunk("c", "third")]
    assert qdrant.scroll.call_args_list[0].args == ("open-webui_kb1",)
    condition = qdrant.scroll.call_args_list[0].kwargs["scroll_filter"].must[0]
    assert (condition.key, condition.match.value) == ("metadata.file_id", "f1")
    assert qdrant.scroll.call_args_list[1].kwargs["offset"] == "next"


def test_chunks_without_a_start_keep_the_order_they_came_in():
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([_point("a", "x"), _point("b", "y")], None)

    assert [chunk.id for chunk in OwuiVectors(qdrant, prefix="p").chunks("kb", "f1")] == ["a", "b"]


@pytest.fixture
def sent(monkeypatch):
    """What the synchronisation sends to the other workers."""
    fake = MagicMock()
    monkeypatch.setattr(tasks.celery_app, "send_task", fake)
    return fake


@pytest.fixture
def run(monkeypatch, sent):
    def _run(file: OwuiFile, chunks: list[OwuiChunk], answer: dict | None = None) -> tuple[dict, dict]:
        owui = MagicMock()
        owui.file.return_value = file
        owui.user.return_value = OwuiUser(
            id="o1", email="a@example.test", name="Alice", oauth={"oidc": {"sub": "kc-1"}}
        )
        owui.file_text.return_value = "The whole text."
        vectors = MagicMock()
        vectors.chunks.return_value = chunks
        backend = MagicMock()
        backend.sync_document.return_value = answer or {"id": "x", "created": True}
        monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
        monkeypatch.setattr(tasks, "OwuiVectors", lambda: vectors)
        monkeypatch.setattr(tasks, "backend_client", backend)
        result = tasks.sync_knowledge_file.run("kb1", "f1")
        vectors.chunks.assert_called_once_with("kb1", "f1")
        source, external_id, body = backend.sync_document.call_args.args
        assert (source, external_id) == ("owui", "kb1/f1")
        return body, result

    return _run


def test_the_file_is_sent_where_it_is_with_its_text_and_chunks(run):
    file = OwuiFile(id="f1", user_id="o1", filename="test.pdf", hash="abc", path="s3://owui-files/f1_test.pdf")

    body, _ = run(file, [OwuiChunk("a", "x" * 40), OwuiChunk("b", "short")])

    assert (body["collection_external_id"], body["name"], body["storage_key"]) == (
        "kb1",
        "test.pdf",
        "s3://owui-files/f1_test.pdf",
    )
    assert (body["content_hash"], body["added_by_user_id"], body["added_by_display"]) == ("abc", "kc-1", "Alice")
    assert body["text"] == "The whole text."
    assert body["chunks"] == [
        {"id": "a", "index": 0, "text": "x" * 40, "token_count": 10},
        {"id": "b", "index": 1, "text": "short", "token_count": 1},
    ]


def test_a_file_that_is_not_in_s3_cannot_be_read_where_it_is(run):
    with pytest.raises(ValueError, match="not in S3"):
        run(OwuiFile(id="f1", filename="a.pdf", path="/app/backend/data/uploads/a.pdf"), [])


FILE = OwuiFile(id="f1", user_id="o1", filename="test.pdf", hash="abc", path="s3://owui-files/f1_test.pdf")


def test_a_file_that_needs_a_summary_has_it_asked_with_the_lowest_priority(run, sent):
    run(FILE, [OwuiChunk("a", "x")], {"id": "doc-1", "collection_id": "col-1", "summary_due": True})

    sent.assert_called_once_with(
        "app.tasks.summarize_copied_document", args=["doc-1", "col-1"], queue="document_enrichment", priority=9
    )


def test_a_file_that_has_its_summary_asks_for_nothing(run, sent):
    run(FILE, [OwuiChunk("a", "x")], {"id": "doc-1", "collection_id": "col-1", "summary_due": False})

    sent.assert_not_called()


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("s3://muffin-documents/f1_test.pdf", "f1_test.pdf"),
        ("s3://muffin-documents/open-webui/f1_test.pdf", "open-webui/f1_test.pdf"),
        ("s3://owui-files/f1_test.pdf", "s3://owui-files/f1_test.pdf"),
    ],
)
def test_a_file_in_the_shared_bucket_keeps_the_key_open_webui_gave_it(run, path, key):
    body, _ = run(OwuiFile(id="f1", user_id="o1", filename="test.pdf", hash="abc", path=path), [OwuiChunk("a", "x")])

    assert body["storage_key"] == key
