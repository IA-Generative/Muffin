import hashlib
import re

from scrapling.fetchers import Fetcher


def fetch_url_markdown(url: str) -> str:
    """Single-level fetch: the page itself, rendered to clean Markdown - no
    following links, no recursive crawl (that's a later phase, if ever)."""
    page = Fetcher.get(url)
    return page.markdown()


def content_hash(markdown: str) -> str:
    """SHA-256 of a page's extracted text, what a scheduled refresh compares to decide whether the
    page changed (#19). Of the extracted Markdown rather than the raw HTML, which changes for reasons
    the text doesn't show (scripts, tokens, ads); and lightly normalized - trailing spaces and runs of
    blank lines - so that layout noise alone doesn't trigger a full reprocessing."""
    lines = [line.rstrip() for line in markdown.strip().splitlines()]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
