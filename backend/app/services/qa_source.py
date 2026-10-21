"""Finds where in its document a QA pair's answer comes from (#126).

A pair generated now carries its page and passage from the start (the worker asks the LLM for the
exact evidence and checks it is really in the text). The older ones don't, so the first time one is
shown as a suggestion its passage is found here, from the document's own chunks, and kept - no LLM,
no vector search: the answer of a generated pair is grounded in the text, so it shares most of its
words with the passage it came from."""

import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.qa import QaPair

# Words shorter than this carry little ("le", "de", "and") and would make every chunk match.
_MIN_WORD = 4
# A passage is only accepted when it shares at least this many distinct words with the answer, and
# this share of them: below that it is a guess, and a guess shown as a source is worse than none.
_MIN_SHARED_WORDS = 3
_MIN_COVERAGE = 0.4
_EXCERPT_MAX_CHARS = 600
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.casefold()) if len(word) >= _MIN_WORD}


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _best_excerpt(text: str, wanted: set[str]) -> str:
    """The one or two consecutive sentences of a chunk that share the most words with the answer."""
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()]
    if not sentences:
        return text[:_EXCERPT_MAX_CHARS].strip()
    windows = [" ".join(sentences[index : index + 2]) for index in range(len(sentences))]
    best = max(windows, key=lambda window: len(_words(window) & wanted))
    return best[:_EXCERPT_MAX_CHARS].strip()


def _page_of(chunk: Chunk) -> int | None:
    page = (chunk.extras or {}).get("page_start")
    return page if isinstance(page, int) and page >= 1 else None


def find_source(qa_pair: QaPair, chunks: Sequence[Chunk]) -> tuple[Chunk, str] | None:
    """The chunk the answer comes from and the passage in it, or None when nothing fits well enough."""
    if qa_pair.source_excerpt:
        wanted_excerpt = _squash(qa_pair.source_excerpt)
        for chunk in chunks:
            if wanted_excerpt in _squash(chunk.text):
                return chunk, qa_pair.source_excerpt
    wanted = _words(qa_pair.answer)
    if len(wanted) < _MIN_SHARED_WORDS:
        return None
    best: Chunk | None = None
    best_shared = 0
    for chunk in chunks:
        shared = len(_words(chunk.text) & wanted)
        if shared > best_shared:
            best, best_shared = chunk, shared
    if best is None or best_shared < _MIN_SHARED_WORDS or best_shared / len(wanted) < _MIN_COVERAGE:
        return None
    return best, _best_excerpt(best.text, wanted)


async def ensure_source(db: AsyncSession, qa_pair: QaPair) -> None:
    """Fills the page, chunk and passage of a pair that lacks them, when they can be found. Left alone
    otherwise - the pair is then shown with its document only."""
    if qa_pair.document_id is None:
        return
    if qa_pair.source_page and qa_pair.source_chunk_id and qa_pair.source_excerpt:
        return
    chunks = (
        (await db.execute(select(Chunk).where(Chunk.document_id == qa_pair.document_id).order_by(Chunk.index)))
        .scalars()
        .all()
    )
    found = find_source(qa_pair, chunks)
    if found is None:
        return
    chunk, excerpt = found
    qa_pair.source_chunk_id = chunk.id
    qa_pair.source_excerpt = excerpt
    qa_pair.source_page = qa_pair.source_page or _page_of(chunk)
    await db.commit()
