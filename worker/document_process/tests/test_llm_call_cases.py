"""The calls to the model that the reference cases of docs/indexing-llm-calls-cases.json promise, counted against what
the worker really does: the tasks it sends and the calls its steps make (#372). The backend checks the same cases
against its estimate (backend/tests/core/test_indexing_cost.py) - so what the interface says a document costs is what
it costs.

Only the cases that read the whole document are run here; the lot that makes the steps read a part of it (#374) runs
the others."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import task_logging, tasks
from app.chunking import PageText, chunk_pages
from app.config import settings as worker_settings
from app.tasks import _shared
from app.tasks import extract as extract_tasks
from app.tasks import qa as qa_tasks
from app.tasks import summarize as summarize_tasks

CASES = json.loads((Path(__file__).parents[3] / "docs" / "indexing-llm-calls-cases.json").read_text())["cases"]
WHOLE_DOCUMENT = [case for case in CASES if not case["sampling"]]


def _settings(case, strategy="paragraph"):
    return {
        "chunking_strategy": strategy,
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "embedder",
        "instructions": {},
        "generation_models": {},
        "pipeline_windows": case["windows"],
    }


def _pages(count):
    return [{"page_number": n, "content": f"Page {n}."} for n in range(1, count + 1)]


@pytest.mark.parametrize("case", WHOLE_DOCUMENT, ids=[case["name"] for case in WHOLE_DOCUMENT])
def test_the_windows_the_worker_sends_are_the_calls_the_case_promises(monkeypatch, case):
    backend = MagicMock()
    backend.get_collection_settings.return_value = _settings(case)
    backend.get_pages.return_value = _pages(case["pages"])
    backend.get_document.return_value = {"content_hash": None}
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    waiting, ran = [], {"qa": 0, "entities": 0}
    monkeypatch.setattr(_shared, "_spawn", lambda task, args, *rest, **kwargs: waiting.append((task, args)))
    monkeypatch.setattr(qa_tasks, "_generate_qa_window", lambda *args: ran.__setitem__("qa", ran["qa"] + 1))
    monkeypatch.setattr(
        extract_tasks, "_extract_entities_window", lambda *args: ran.__setitem__("entities", ran["entities"] + 1)
    )
    monkeypatch.setattr(worker_settings, "ENRICHMENT_WINDOW", 4)

    tasks.chunk_document("doc-1", "col-1")
    while waiting:
        task, args = waiting.pop(0)
        if task is not summarize_tasks.summarize_document:
            task(*args)

    assert ran["qa"] == case["chat"]["qa"]
    assert ran["entities"] == case["chat"]["entities"]


@pytest.mark.parametrize("case", WHOLE_DOCUMENT, ids=[case["name"] for case in WHOLE_DOCUMENT])
def test_the_summary_makes_the_calls_the_case_promises(monkeypatch, case):
    calls = []
    backend = MagicMock()
    backend.get_pages.return_value = _pages(case["pages"])
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(_shared, "_chat", lambda model, system, content: calls.append(system) or "summary")

    summarize_tasks._summarize("doc-1", {**_settings(case), "embedding_model": "embedder"}, "model")

    assert len(calls) == case["chat"]["summary"]


@pytest.mark.parametrize("case", WHOLE_DOCUMENT, ids=[case["name"] for case in WHOLE_DOCUMENT])
def test_the_chunking_asks_the_model_only_with_that_strategy(case):
    asked = []
    pages = [PageText(page_number=row["page_number"], content=row["content"]) for row in _pages(case["pages"])]
    window = {**_shared.PIPELINE_WINDOW_DEFAULTS, **case["windows"]}["chunking_window_pages"]

    def chunk_starts(paragraphs):
        asked.append(paragraphs)
        return [0]

    chunk_pages(pages, "llm", 500, 50, window_pages=window, slide_pages=1, chunk_starts=chunk_starts)

    expected = -(-case["pages"] // window)
    assert len(asked) == expected
    assert (case["chat"]["chunking"] == expected) == (case["chunking_strategy"] == "llm")
