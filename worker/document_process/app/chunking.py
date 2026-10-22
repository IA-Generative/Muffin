import re
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger

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


def _chunk_fixed(pages: list[PageText], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    text, offsets = _concat_with_offsets(pages)
    chunk_size = max(chunk_size, 1)
    stride = max(chunk_size - chunk_overlap, 1)

    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        segment = text[start:end].strip()
        if segment:
            chunks.append(
                Chunk(
                    text=segment,
                    page_start=_page_for_offset(offsets, start),
                    page_end=_page_for_offset(offsets, max(end - 1, start)),
                )
            )
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
        stripped = paragraph.strip()
        if stripped:
            chunks.append(
                Chunk(
                    text=stripped,
                    page_start=_page_for_offset(offsets, start),
                    page_end=_page_for_offset(offsets, start + len(paragraph)),
                )
            )
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
        for chunk in _chunk_paragraphs(window_pages_text):
            chunks.append(Chunk(text=chunk.text, page_start=start_page, page_end=end_page))
    return chunks


# Given a window's paragraphs, in order, the indices of those a new chunk starts at - what the LLM decides.
ChunkStarts = Callable[[list[str]], list[int]]


def _chunk_llm(pages: list[PageText], window_pages: int, chunk_starts: ChunkStarts) -> list[Chunk]:
    """An LLM decides where the chunks of each window of pages begin - windows side by side, so that no
    text lands in two chunks. It only picks among the window's paragraphs, never rewrites them: a chunk
    is always the document's own text, consecutive paragraphs joined. A window it fails on (an error,
    an answer that isn't a list of paragraph indices) is cut by paragraph instead."""
    chunks: list[Chunk] = []
    window_pages = max(window_pages, 1)
    for start in range(0, len(pages), window_pages):
        paragraphs = _chunk_paragraphs(pages[start : start + window_pages])
        if not paragraphs:
            continue
        try:
            starts = _valid_starts(chunk_starts([paragraph.text for paragraph in paragraphs]), len(paragraphs))
        except Exception as error:
            logger.warning(f"LLM chunking failed on pages {pages[start].page_number}+, cut by paragraph: {error}")
            starts = list(range(len(paragraphs)))
        for first, end in zip(starts, [*starts[1:], len(paragraphs)], strict=True):
            group = paragraphs[first:end]
            chunks.append(
                Chunk(
                    text="\n\n".join(paragraph.text for paragraph in group),
                    page_start=group[0].page_start,
                    page_end=group[-1].page_end,
                )
            )
    return chunks


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
) -> list[Chunk]:
    """`chunk_starts`: how the "llm" strategy asks the model - without one (no model available), the
    document is cut by paragraph."""
    if not pages:
        return []
    if strategy == "fixed":
        return _chunk_fixed(pages, chunk_size, chunk_overlap)
    if strategy == "semantic":
        return _chunk_semantic(pages, window_pages, slide_pages)
    if strategy == "llm" and chunk_starts is not None:
        return _chunk_llm(pages, window_pages, chunk_starts)
    return _chunk_paragraphs(pages)
