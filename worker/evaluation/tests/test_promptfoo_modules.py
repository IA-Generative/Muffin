import json
from unittest.mock import MagicMock

from app.promptfoo import create_tests, provider

# The provider runs in a promptfoo-spawned subprocess: everything it needs arrives via
# options["config"] - these tests pin down that contract (and the YAML's with it).
_PROVIDER_CONFIG = {
    "backend_url": "http://backend:8000",
    "api_key_envar": "WORKER_API_KEY",
    "collection_id": "col-1",
    "k": 5,
    "generator_model": "generator-model",
}


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


def test_the_provider_answers_plainly_when_nothing_is_retrieved(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _response([])

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    monkeypatch.setenv("WORKER_API_KEY", "the-key")

    result = provider.call_api("Une question ?", {"config": dict(_PROVIDER_CONFIG)}, {})

    assert result["output"]["answer"] == "No relevant excerpts were retrieved for this question."
    # A placeholder context keeps the factuality grader well-formed rather than empty.
    assert result["context"] == ["no context retrieved"]
    assert result["metadata"]["sources"] == []
    # Nothing retrieved: no generation call at all.
    assert len(calls) == 1


def test_the_provider_searches_then_generates_and_formats_sources(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/internal/search"):
            return _response(
                [
                    {"text": "extrait 1", "document_name": "doc-a.pdf", "chunk_id": "c1"},
                    {"text": "extrait 2", "document_name": "doc-b.pdf", "chunk_id": "c2"},
                ]
            )
        return _response({"content": "La réponse."})

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    monkeypatch.setenv("WORKER_API_KEY", "the-key")

    result = provider.call_api("Une question ?", {"config": dict(_PROVIDER_CONFIG)}, {})

    assert result["output"]["answer"] == "La réponse."
    assert result["output"]["context"] == ["extrait 1", "extrait 2"]
    # The evaluations UI shows the sources as document_name#chunk_id, same format as before.
    assert result["metadata"]["sources"] == ["doc-a.pdf#c1", "doc-b.pdf#c2"]

    search_url, search_kwargs = calls[0]
    assert search_url == "http://backend:8000/api/internal/search"
    assert search_kwargs["json"] == {
        "collection_ids": ["col-1"],
        "query": "Une question ?",
        "limit": 5,
    }
    assert search_kwargs["headers"] == {"X-API-Key": "the-key"}

    chat_url, chat_kwargs = calls[1]
    assert chat_url == "http://backend:8000/api/internal/llm/chat"
    assert chat_kwargs["json"]["model"] == "generator-model"
    assert chat_kwargs["json"]["usage"] == {"collection_id": "col-1"}
    user_message = chat_kwargs["json"]["messages"][1]["content"]
    assert "Une question ?" in user_message
    assert "extrait 1" in user_message


def test_the_provider_reads_the_key_from_the_configured_envar(monkeypatch):
    # The key is never in the YAML (promptfoo replays it into the stored results.json):
    # the config only names the environment variable to read.
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _response([])

    monkeypatch.setattr(provider.httpx, "post", fake_post)
    monkeypatch.setenv("A_CUSTOM_ENVAR", "another-key")

    config = dict(_PROVIDER_CONFIG, api_key_envar="A_CUSTOM_ENVAR")
    provider.call_api("q", {"config": config}, {})

    assert captured["headers"] == {"X-API-Key": "another-key"}


def test_create_tests_maps_pairs_to_factuality_tests(tmp_path):
    pairs_file = tmp_path / "pairs.json"
    pairs_file.write_text(
        json.dumps(
            [
                {"id": "qa-1", "question": "Q ?", "answer": "A.", "validated": True, "golden": False},
                {"id": "qa-2", "question": "Q2 ?", "answer": "A2.", "validated": False, "golden": True},
            ]
        )
    )

    tests = create_tests.create_tests({"pairs_file": str(pairs_file)})

    assert tests[0]["vars"] == {
        "question": "Q ?",
        "reference": "A.",
        "validated": True,
        "golden": False,
        "qa_pair_id": "qa-1",
    }
    assert tests[1]["vars"]["golden"] is True
    # The threshold colors a low score in the report - it never drops the result.
    for test, answer in zip(tests, ["A.", "A2."], strict=True):
        assert test["assert"] == [{"type": "factuality", "value": answer, "threshold": 0.7, "metric": "factuality"}]
