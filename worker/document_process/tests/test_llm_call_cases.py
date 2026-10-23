"""The calls to the model that the reference cases of docs/indexing-llm-calls-cases.json promise, counted against what
the worker really does: the tasks it sends and the calls its steps make (#372). The backend checks the same cases
against its estimate (backend/tests/core/test_indexing_cost.py) - so what the interface says a document costs is what
it costs.

Every case is run, the ones that read a part of a long document (#372) included."""

import json
import re
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
WHOLE_DOCUMENT = CASES


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
    # Enough text in each page for a window to be worth reading (sampling.MIN_TEXT_CHARS).
    return [{"page_number": n, "content": f"Page {n}. " + "Some text on the page. " * 4} for n in range(1, count + 1)]


@pytest.mark.parametrize("case", WHOLE_DOCUMENT, ids=[case["name"] for case in WHOLE_DOCUMENT])
def test_the_windows_the_worker_sends_are_the_calls_the_case_promises(monkeypatch, case):
    backend = MagicMock()
    backend.get_collection_settings.return_value = _settings(case)
    backend.get_pages.return_value = _pages(case["pages"])
    backend.get_document.return_value = {"content_hash": None}
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    waiting, ran = [], {"qa": 0, "entities": 0, "questions": 0, "windows": []}
    monkeypatch.setattr(_shared, "_spawn", lambda task, args, *rest, **kwargs: waiting.append((task, args)))

    def qa_window(document_id, collection_id, start, end, questions):
        ran["qa"] += 1
        ran["questions"] += questions
        ran["windows"].append((start, end))

    monkeypatch.setattr(qa_tasks, "_generate_qa_window", qa_window)
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
    # The questions asked, which is what a cap is held to.
    assert ran["questions"] == case["embeddings"]["qa_questions"]
    assert len(set(ran["windows"])) == len(ran["windows"])
    if case["sampling"]:
        # What earlier runs derived from windows no longer read is removed - leaving the ones read alone.
        kept = {}
        for call in backend.prune_windows.call_args_list:
            kept.update(call.kwargs)
        for step, key in (("qa", "qa"), ("entities", "entities")):
            if key in kept:
                assert len(kept[key]) == case["chat"][step]
        if "qa" in kept:
            assert {f"window:{start}-{end}" for start, end in ran["windows"]} == set(kept["qa"])
    else:
        backend.prune_windows.assert_not_called()


@pytest.mark.parametrize("case", WHOLE_DOCUMENT, ids=[case["name"] for case in WHOLE_DOCUMENT])
def test_the_summary_makes_the_calls_the_case_promises(monkeypatch, case):
    calls = []
    backend = MagicMock()
    backend.get_pages.return_value = _pages(case["pages"])
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(_shared, "_chat", lambda model, system, content: calls.append(system) or "summary")

    summarize_tasks._summarize("doc-1", {**_settings(case), "embedding_model": "embedder"}, "model")

    assert len(calls) == case["chat"]["summary"]


def test_a_partial_summary_reads_only_its_stretches_and_says_so(monkeypatch):
    calls = []
    backend = MagicMock()
    backend.get_pages.return_value = _pages(300)
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(_shared, "_chat", lambda model, system, content: calls.append((system, content)) or "summary")
    settings = {
        "instructions": {},
        "embedding_model": "embedder",
        "pipeline_windows": {
            "sampling_min_pages": 100,
            "summary_mode": "percent",
            "summary_percent": 20,
            "summary_pages_per_map": 5,
        },
    }

    summarize_tasks._summarize("doc-1", settings, "model")

    read = {int(page) for _, content in calls[:-1] for page in re.findall(r"Page (\d+)\.", content)}
    assert read == set(range(1, 31)) | set(range(271, 301))
    # No map batch straddles the two stretches: 30 pages = 6 batches of 5, twice, then one reduce.
    assert len(calls) == 13
    assert "Only pages 1-30, 271-300 of this 300-page document" in calls[-1][0]
    assert backend.set_document_summary.call_args.kwargs["pages"] == [(1, 30), (271, 300)]


def test_a_whole_document_summary_is_not_flagged_partial(monkeypatch):
    calls = []
    backend = MagicMock()
    backend.get_pages.return_value = _pages(10)
    monkeypatch.setattr(_shared, "backend_client", backend)
    monkeypatch.setattr(_shared, "_chat", lambda model, system, content: calls.append(system) or "summary")

    summarize_tasks._summarize("doc-1", {"instructions": {}, "embedding_model": "embedder"}, "model")

    assert all("Only pages" not in system for system in calls)
    assert backend.set_document_summary.call_args.kwargs["pages"] is None


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
