import re
from dataclasses import dataclass

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


def chunk_pages(
    pages: list[PageText],
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    window_pages: int,
    slide_pages: int,
) -> list[Chunk]:
    if not pages:
        return []
    if strategy == "fixed":
        return _chunk_fixed(pages, chunk_size, chunk_overlap)
    if strategy == "semantic":
        return _chunk_semantic(pages, window_pages, slide_pages)
    # "paragraph" and "llm" (a real LLM-driven splitter isn't implemented
    # yet) both fall back to plain paragraph splitting.
    return _chunk_paragraphs(pages)
