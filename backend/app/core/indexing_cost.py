"""How many calls to the language model indexing a document costs (#372) - what a collection's settings say, for a
document of that many pages.

The formulas are those of docs/indexing-llm-calls.md. They are here once, for the interface (GET
/api/collections/{id}/indexing-estimate); the cases of docs/indexing-llm-calls-cases.json are checked against them
here and against the tasks the worker really sends (worker/document_process/tests/test_llm_call_cases.py), so the
two cannot drift apart. A call to the chat model is what is counted; embeddings are given apart."""

import math
from typing import Any

from app.core.page_ranges import parse_page_ranges

# The most the collection's description, tags and reference questions add for a document - and only when its
# summary changes what the collection says.
COLLECTION_CALLS_MAX = 4


def sliding_windows(total_pages: int, window_pages: int, slide_pages: int) -> int:
    """How many windows of `window_pages` pages sliding by `slide_pages` cover the document (always one at least)."""
    if total_pages <= 0:
        return 0
    window_pages, slide_pages = max(window_pages, 1), max(slide_pages, 1)
    if total_pages <= window_pages:
        return 1
    return math.ceil((total_pages - window_pages) / slide_pages) + 1


def _disjoint(total_pages: int, window_pages: int) -> int:
    return sliding_windows(total_pages, window_pages, window_pages)


def sampled(pages: int, windows: dict[str, Any]) -> bool:
    """Whether the document is long enough for the settings that read only a part of it to apply."""
    return pages > windows["sampling_min_pages"]


def _summary_segments(pages: int, windows: dict[str, Any]) -> list[tuple[int, int]] | None:
    """The stretches of pages the summary reads (None: all) - the worker's sampling.summary_segments."""
    mode = windows["summary_mode"]
    if mode == "all" or not sampled(pages, windows):
        return None
    if mode == "percent":
        head, tail = windows.get("summary_head_percent"), windows.get("summary_tail_percent")
        if head is not None or tail is not None:
            head_pages = math.ceil(pages * (head or 0) / 100)
            tail_pages = math.ceil(pages * (tail or 0) / 100)
        else:
            read = math.ceil(pages * windows["summary_percent"] / 100)
            head_pages = math.ceil(read / 2)
            tail_pages = read - head_pages
        segments = []
        if head_pages:
            segments.append((1, head_pages))
        if tail_pages:
            segments.append((pages - tail_pages + 1, pages))
    else:
        segments = [
            (first, min(last if last is not None else pages, pages))
            for first, last in parse_page_ranges(windows["summary_page_ranges"])
            if first <= pages
        ]
    merged: list[tuple[int, int]] = []
    for start, end in sorted(segments):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if not merged or sum(end - start + 1 for start, end in merged) >= pages:
        return None
    return merged


def _summary_calls(pages: int, windows: dict[str, Any]) -> int:
    """One call per batch of `summary_pages_per_map` pages - in each stretch read - then one to combine them."""
    per_map = max(windows["summary_pages_per_map"], 1)
    segments = _summary_segments(pages, windows) or [(1, pages)]
    batches = sum(math.ceil((end - start + 1) / per_map) for start, end in segments)
    return batches + (1 if batches > 1 else 0)


def _qa(pages: int, windows: dict[str, Any]) -> tuple[int, int]:
    """(windows asked, questions at most) - one call per window."""
    per_window = windows["qa_questions_per_window"]
    max_questions = windows.get("qa_max_questions")
    if not sampled(pages, windows) or max_questions is None:
        count = sliding_windows(pages, windows["qa_window_pages"], windows["qa_slide_pages"])
        return count, count * per_window
    available = _disjoint(pages, windows["qa_window_pages"])
    if max_questions < per_window:
        count, asked = min(1, available), max(max_questions, 1)
    else:
        count, asked = min(available, max_questions // per_window), per_window
    return count, count * asked


def _entity_windows(pages: int, windows: dict[str, Any]) -> int:
    percent, cap = windows["extraction_percent"], windows.get("extraction_max_windows")
    if not sampled(pages, windows) or (percent >= 100 and cap is None):
        return sliding_windows(pages, windows["extraction_window_pages"], windows["extraction_slide_pages"])
    available = _disjoint(pages, windows["extraction_window_pages"])
    wanted = max(1, math.ceil(available * percent / 100))
    return min(wanted if cap is None else min(wanted, cap), available)


def estimate_llm_calls(pages: int, windows: dict[str, Any], chunking_strategy: str = "recursive") -> dict[str, Any]:
    """The calls a document of `pages` pages costs under these settings (the collection's pipeline windows, every
    key present). Chunking asks the model only with the "llm" strategy."""
    qa_calls, qa_questions = _qa(pages, windows)
    chat = {
        "chunking": math.ceil(pages / max(windows["chunking_window_pages"], 1)) if chunking_strategy == "llm" else 0,
        "summary": _summary_calls(pages, windows),
        "tagging": 1,
        "qa": qa_calls,
        "entities": _entity_windows(pages, windows),
    }
    return {
        "pages": pages,
        "sampled": sampled(pages, windows),
        "chat": {**chat, "total": sum(chat.values())},
        # Calls to the embedding model that do not depend on how the text is cut: the summary, and a question each.
        "embeddings": {"summary": 1, "qa_questions": qa_questions},
        "collection_max": COLLECTION_CALLS_MAX,
    }
