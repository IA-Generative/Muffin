"""The "llm" chunking strategy: a model decides where the chunks begin, among the document's paragraphs."""

from unittest.mock import MagicMock

import pytest

from app import reuse, task_logging, tasks
from app.chunking import PageText, chunk_pages

PAGES = [
    PageText(page_number=1, content="# Titre\n\nIntro.\n\nSuite de l'intro."),
    PageText(page_number=2, content="## Partie 2\n\nDétail."),
]


def _chunk(chunk_starts, pages=PAGES, window_pages=2):
    return chunk_pages(pages, "llm", 500, 50, window_pages=window_pages, slide_pages=1, chunk_starts=chunk_starts)


def test_chunks_are_the_paragraphs_grouped_where_the_model_says_they_begin():
    seen = []

    def chunk_starts(paragraphs):
        seen.append(paragraphs)
        return [0, 3]

    chunks = _chunk(chunk_starts)

    assert seen == [["# Titre", "Intro.", "Suite de l'intro.", "## Partie 2", "Détail."]]
    assert [(chunk.text, chunk.page_start, chunk.page_end) for chunk in chunks] == [
        ("# Titre\n\nIntro.\n\nSuite de l'intro.", 1, 1),
        ("## Partie 2\n\nDétail.", 2, 2),
    ]


def test_each_window_of_pages_is_asked_on_its_own_and_no_text_is_in_two_chunks():
    calls = []
    chunks = _chunk(lambda paragraphs: calls.append(paragraphs) or [0], window_pages=1)

    assert len(calls) == 2
    assert [chunk.text for chunk in chunks] == ["# Titre\n\nIntro.\n\nSuite de l'intro.", "## Partie 2\n\nDétail."]


@pytest.mark.parametrize("answer", [[1, 3], [3, 1, 3]])
def test_the_first_paragraph_always_starts_a_chunk_and_the_starts_are_put_in_order(answer):
    chunks = _chunk(lambda paragraphs: answer, window_pages=2)

    assert [chunk.text.split("\n\n")[0] for chunk in chunks] == ["# Titre", "Intro.", "## Partie 2"]


@pytest.mark.parametrize("answer", [[0, 99], [0, -1], ["0", "3"], {"starts": [0]}])
def test_an_answer_that_is_not_paragraph_numbers_cuts_the_window_by_paragraph(answer):
    chunks = _chunk(lambda paragraphs: answer)

    assert len(chunks) == 5


def test_a_model_that_fails_cuts_the_window_by_paragraph():
    def chunk_starts(paragraphs):
        raise ValueError("Model 'chat' returned invalid JSON")

    assert len(_chunk(chunk_starts)) == 5


def test_without_a_model_the_llm_strategy_cuts_by_paragraph():
    assert len(_chunk(None)) == 5


def _settings(**changes):
    return {
        "chunking_strategy": "llm",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "embedder",
        "instructions": {"chunking": "Ne jamais couper une clause en deux."},
        "generation_models": {"chunking": "chunker"},
        "pipeline_windows": {},
        **changes,
    }


def test_the_chunk_task_asks_the_collections_chunking_model_with_its_instructions(monkeypatch):
    backend = MagicMock()
    backend.get_collection_settings.return_value = _settings()
    backend.get_pages.return_value = [{"page_number": 1, "content": "Un.\n\nDeux.\n\nTrois."}]
    backend.get_document.return_value = {"content_hash": None}
    backend.llm_chat.return_value = "```json\n[0, 2]\n```"
    monkeypatch.setattr(tasks._shared, "backend_client", backend)
    monkeypatch.setattr(task_logging, "backend_client", MagicMock())
    monkeypatch.setattr(tasks._shared, "_spawn", MagicMock())

    tasks.chunk_document("doc-1", "col-1")

    model, messages = backend.llm_chat.call_args.args
    assert model == "chunker"
    assert messages[0]["content"].startswith("Ne jamais couper une clause en deux.")
    assert messages[1]["content"] == "[0] Un.\n\n[1] Deux.\n\n[2] Trois."
    assert [call.kwargs["text"] for call in backend.add_chunk.call_args_list] == ["Un.\n\nDeux.", "Trois."]


def test_llm_chunks_are_reused_only_under_the_same_model_and_instructions(monkeypatch):
    monkeypatch.setattr(tasks._shared, "backend_client", MagicMock())
    file = "a" * 64

    assert reuse.chunks(file, _settings()) == reuse.chunks(file, _settings())
    assert reuse.chunks(file, _settings()) != reuse.chunks(file, _settings(generation_models={"chunking": "other"}))
    assert reuse.chunks(file, _settings()) != reuse.chunks(file, _settings(instructions={"chunking": "Autre."}))


def test_windows_asked_at_once_still_give_the_chunks_in_the_documents_order():
    import threading
    import time

    pages = [PageText(page_number=n, content=f"Page {n}.") for n in range(1, 21)]
    seen_threads = set()

    def chunk_starts(paragraphs):
        seen_threads.add(threading.get_ident())
        # The first windows answer last.
        time.sleep(0.05 if paragraphs[0] in ("Page 1.", "Page 2.") else 0)
        return [0]

    chunks = chunk_pages(pages, "llm", 500, 50, window_pages=1, slide_pages=1, chunk_starts=chunk_starts, concurrency=4)

    assert [chunk.text for chunk in chunks] == [f"Page {n}." for n in range(1, 21)]
    assert len(seen_threads) > 1
