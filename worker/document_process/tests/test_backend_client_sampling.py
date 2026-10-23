from unittest.mock import MagicMock

import pytest

from app.backend_client import BackendClient


@pytest.fixture
def client(monkeypatch):
    backend = BackendClient()
    monkeypatch.setattr(backend, "_client", MagicMock())
    return backend


def test_a_summary_of_the_whole_document_says_no_pages(client):
    client.set_document_summary("doc-1", "Summary.", [0.1])

    json = client._client.patch.call_args.kwargs["json"]
    assert json["pages"] is None and json["summary"] == "Summary."


def test_a_summary_of_a_part_says_which_pages(client):
    client.set_document_summary("doc-1", "Summary.", None, pages=[(1, 135), (766, 900)])

    assert client._client.patch.call_args.kwargs["json"]["pages"] == [[1, 135], [766, 900]]


def test_pruning_asks_to_keep_the_windows_given_and_leaves_a_step_out_with_none(client):
    client.prune_windows("doc-1", qa=["window:1-2"])

    url = client._client.post.call_args.args[0]
    assert url == "/api/internal/documents/doc-1/windows/prune"
    assert client._client.post.call_args.kwargs["json"] == {"qa": ["window:1-2"], "entities": None}

    client.prune_windows("doc-1", entities=["pages:1-4"])
    assert client._client.post.call_args.kwargs["json"] == {"qa": None, "entities": ["pages:1-4"]}
