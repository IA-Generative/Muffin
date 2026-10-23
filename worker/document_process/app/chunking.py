import contextvars
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from loguru import logger

from app.task_revocation import TaskRevoked
from app.windows import sliding_windows

TOKENS_PER_CHAR = 0.25  # rough estimate, good enough until a real tokenizer is wired in
PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")


@dataclass
class PageText:
    page_number: int
    content: str


@dataclass
class Chunk:
    text: str
    page_start: int
    page_end: int
    # Where the chunk is in the pages (#353): for each page it touches, the interval of characters in that
    # page's own content - [{"page": 3, "start": 120, "end": 560}, ...]. Intervals, not rectangles: the boxes of
    # a page's lines say where those characters are, so a chunk is framed at its exact place, even when the same
    # words are there twice. `page_start`/`page_end` are the first and last of these pages.
    spans: list[dict[str, int]] = field(default_factory=list)


def _page_for_offset(offsets: list[tuple[int, int]], char_offset: int) -> int:
    """offsets is [(page_number, cumulative_start_offset), ...] sorted by
    offset - finds the page a given character position falls in."""
    page_number = offsets[0][0]
    for number, start in offsets:
        if char_offset < start:
            break
        page_number = number
    return page_number


def _concat_with_offsets(pages: list[PageText]) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page in pages:
        offsets.append((page.page_number, cursor))
        parts.append(page.content)
        cursor += len(page.content) + 2  # +2 for the "\n\n" joiner below
    return "\n\n".join(parts), offsets


def _spans(pages: list[PageText], offsets: list[tuple[int, int]], start: int, end: int) -> list[dict[str, int]]:
    """The interval [start, end) of the pages joined together (see `_concat_with_offsets`), as one interval of
    characters per page it touches, relative to that page's own content - the joiner between pages is in none."""
    spans = []
    for page, (number, page_start) in zip(pages, offsets, strict=True):
        low, high = max(start, page_start), min(end, page_start + len(page.content))
        if low < high:
            spans.append({"page": number, "start": low - page_start, "end": high - page_start})
    return spans


def _chunk_of(text: str, pages: list[PageText], offsets: list[tuple[int, int]], start: int) -> Chunk:
    """The chunk made of `text`, which `text.strip()` is at `start` in the joined pages: its blanks are not part of
    it, so the interval it covers is shifted past them."""
    stripped = text.strip()
    first = start + len(text) - len(text.lstrip())
    spans = _spans(pages, offsets, first, first + len(stripped))
    if not spans:
        # Nothing of the pages (the text is made of the joiner alone): the page it was cut at.
        page = _page_for_offset(offsets, first)
        return Chunk(text=stripped, page_start=page, page_end=page)
    return Chunk(text=stripped, page_start=spans[0]["page"], page_end=spans[-1]["page"], spans=spans)


def _chunk_fixed(pages: list[PageText], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    text, offsets = _concat_with_offsets(pages)
    chunk_size = max(chunk_size, 1)
    stride = max(chunk_size - chunk_overlap, 1)

    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        segment = text[start:end]
        if segment.strip():
            chunks.append(_chunk_of(segment, pages, offsets, start))
        if end >= len(text):
            break
        start += stride
    return chunks


def _chunk_paragraphs(pages: list[PageText]) -> list[Chunk]:
    text, offsets = _concat_with_offsets(pages)
    chunks: list[Chunk] = []
    cursor = 0
    for paragraph in PARAGRAPH_SPLIT.split(text):
        start = text.index(paragraph, cursor) if paragraph else cursor
        if paragraph.strip():
            chunks.append(_chunk_of(paragraph, pages, offsets, start))
        cursor = start + len(paragraph)
    return chunks


def _chunk_semantic(pages: list[PageText], window_pages: int, slide_pages: int) -> list[Chunk]:
    """Real embedding-based semantic segmentation (cosine similarity between
    consecutive sentences) isn't wired in yet - this approximates it by
    paragraph-splitting within each sliding page window, which at least keeps
    chunks bounded to a topic-coherent slice of the document instead of the
    whole thing at once."""
    by_page = {page.page_number: page for page in pages}
    chunks: list[Chunk] = []
    for start_page, end_page in sliding_windows(len(pages), window_pages, slide_pages):
        window_pages_text = [by_page[n] for n in range(start_page, end_page + 1) if n in by_page]
        # A chunk's own pages: it is a paragraph of the window, not the whole window.
        chunks.extend(_chunk_paragraphs(window_pages_text))
    return chunks


# Given a window's paragraphs, in order, the indices of those a new chunk starts at - what the LLM decides.
ChunkStarts = Callable[[list[str]], list[int]]


def _chunk_llm(
    pages: list[PageText], window_pages: int, chunk_starts: ChunkStarts, concurrency: int = 1
) -> list[Chunk]:
    """An LLM decides where the chunks of each window of pages begin - windows side by side, so that no
    text lands in two chunks. It only picks among the window's paragraphs, never rewrites them: a chunk
    is always the document's own text, consecutive paragraphs joined. A window it fails on (an error,
    an answer that isn't a list of paragraph indices) is cut by paragraph instead.

    `concurrency` windows are asked at once: a long document is hundreds of windows, one after the
    other they would take hours. The chunks come out in the document's order all the same."""
    window_pages = max(window_pages, 1)
    windows = [_chunk_paragraphs(pages[start : start + window_pages]) for start in range(0, len(pages), window_pages)]
    windows = [paragraphs for paragraphs in windows if paragraphs]

    def starts_of(paragraphs: list[Chunk]) -> list[int] | None:
        """None when the model failed on the window."""
        try:
            return _valid_starts(chunk_starts([paragraph.text for paragraph in paragraphs]), len(paragraphs))
        except TaskRevoked:
            raise
        except Exception as error:
            logger.warning(f"LLM chunking failed on pages {paragraphs[0].page_start}+, cut by paragraph: {error}")
            return None

    with ThreadPoolExecutor(max_workers=max(concurrency, 1)) as pool:
        # Each call in a copy of this context: its lines stay the task's (see app/task_logging.py).
        futures = [pool.submit(contextvars.copy_context().run, starts_of, paragraphs) for paragraphs in windows]
        answers = [future.result() for future in futures]
    if windows:
        failed = sum(answer is None for answer in answers)
        logger.info(f"LLM chunking: {len(windows)} window(s) of pages, {failed} cut by paragraph instead")
    all_starts = [
        list(range(len(paragraphs))) if starts is None else starts
        for paragraphs, starts in zip(windows, answers, strict=True)
    ]

    chunks: list[Chunk] = []
    for paragraphs, starts in zip(windows, all_starts, strict=True):
        for first, end in zip(starts, [*starts[1:], len(paragraphs)], strict=True):
            group = paragraphs[first:end]
            chunks.append(
                Chunk(
                    text="\n\n".join(paragraph.text for paragraph in group),
                    page_start=group[0].page_start,
                    page_end=group[-1].page_end,
                    spans=_merge_spans([span for paragraph in group for span in paragraph.spans]),
                )
            )
    return chunks


def _merge_spans(spans: list[dict[str, int]]) -> list[dict[str, int]]:
    """The intervals of consecutive paragraphs, as one per page: from where the first begins to where the last
    ends on that page - the blanks between them are in the chunk's region of the page."""
    by_page: dict[int, dict[str, int]] = {}
    for span in spans:
        merged = by_page.setdefault(span["page"], dict(span))
        merged["start"] = min(merged["start"], span["start"])
        merged["end"] = max(merged["end"], span["end"])
    return [by_page[page] for page in sorted(by_page)]


def _valid_starts(starts: list[int], count: int) -> list[int]:
    """The indices sorted and deduplicated, the first paragraph always one. Refused when not indices of
    the window's paragraphs: then the model didn't do what it was asked, nothing it says is trusted."""
    if not isinstance(starts, list) or not all(isinstance(index, int) and 0 <= index < count for index in starts):
        raise ValueError(f"not a list of paragraph indices between 0 and {count - 1}: {starts!r}")
    return sorted({0, *starts})


def chunk_pages(
    pages: list[PageText],
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    window_pages: int,
    slide_pages: int,
    chunk_starts: ChunkStarts | None = None,
    concurrency: int = 1,
) -> list[Chunk]:
    """`chunk_starts`: how the "llm" strategy asks the model - without one (no model available), the
    document is cut by paragraph. `concurrency`: how many windows it is asked about at once."""
    if not pages:
        return []
    if strategy == "fixed":
        return _chunk_fixed(pages, chunk_size, chunk_overlap)
    if strategy == "semantic":
        return _chunk_semantic(pages, window_pages, slide_pages)
    if strategy == "llm" and chunk_starts is not None:
        return _chunk_llm(pages, window_pages, chunk_starts, concurrency)
    return _chunk_paragraphs(pages)
