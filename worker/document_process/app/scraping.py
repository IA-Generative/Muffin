import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from scrapling.fetchers import Fetcher

from app.config import settings
from app.zip_import import SUPPORTED_EXTENSIONS

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
# What mimetypes doesn't know, or guesses differently from the extension the pipeline expects.
_EXTENSION_BY_CONTENT_TYPE = {
    "text/markdown": ".md",
    "text/plain": ".txt",
    "application/jsonl": ".jsonl",
    "application/x-ndjson": ".jsonl",
    "application/vnd.apache.parquet": ".parquet",
    "image/jpeg": ".jpg",
}


class UnsupportedUrlContentError(Exception):
    """The URL serves a file the pipeline can't process (an archive, a video...)."""


class UrlFetchError(Exception):
    """The site answered, but not with the page: an HTTP error, or an anti-bot challenge in its place.
    Neither is the document - indexed, it would be a page saying "Just a moment..." or "Not found". The
    message is shown with the document, hence in French."""


# The titles of the pages anti-bot services answer with instead of the content (Cloudflare's, mostly).
_CHALLENGE_TITLES = (b"<title>just a moment", b"<title>attention required", b"<title>un instant")


@dataclass(frozen=True)
class FetchedUrl:
    """What a URL served: an HTML page rendered to Markdown, or a file (`data`, named `filename` after
    its format) that goes through the same processing as an upload - liteparse, tabular, text."""

    markdown: str = ""
    data: bytes | None = None
    filename: str = ""
    content_type: str = ""

    @property
    def content_hash(self) -> str:
        # A file is compared byte for byte: hashing its text would mean parsing (and OCR-ing) it at
        # every refresh check, just to find out whether anything changed.
        if self.data is not None:
            return hashlib.sha256(self.data).hexdigest()
        return content_hash(self.markdown)


def fetch_url(url: str) -> FetchedUrl:
    """Single-level fetch: the page itself - no following links, no recursive crawl (that's a later
    phase, if ever)."""
    # A (connect, read) pair: curl then fails fast on a site it can't reach, and gives the download -
    # a large file served by the URL included - all the time it needs, up to their sum. A single value
    # would be one deadline for both: short, a large PDF never fits in; long, a site down hangs the task.
    page = Fetcher.get(url, timeout=(settings.URL_FETCH_CONNECT_TIMEOUT_SECONDS, settings.URL_FETCH_TIMEOUT_SECONDS))
    _check_answer(page)
    content_type = next((str(value) for key, value in page.headers.items() if key.lower() == "content-type"), "")
    content_type = content_type.split(";")[0].strip().lower()
    if content_type in _HTML_CONTENT_TYPES or (not content_type and page.body.lstrip()[:1] == b"<"):
        return FetchedUrl(markdown=page.markdown())
    return FetchedUrl(
        data=page.body,
        filename=_filename(url, content_type, page.body),
        content_type=content_type or "application/octet-stream",
    )


def _check_answer(page) -> None:
    """Raises UrlFetchError when what came back isn't the page: Fetcher hands back an error page or a
    challenge like any other, with its status."""
    headers = {str(key).lower(): str(value) for key, value in page.headers.items()}
    head = page.body[:4096].lower()
    if headers.get("cf-mitigated") == "challenge" or (
        page.status in (403, 429, 503) and any(title in head for title in _CHALLENGE_TITLES)
    ):
        raise UrlFetchError(
            f"Le site protège cette page contre les robots (réponse {page.status}) : elle n'a pas pu être récupérée."
        )
    if page.status >= 400:
        raise UrlFetchError(f"Le site a répondu {page.status} : la page n'a pas pu être récupérée.")


def _filename(url: str, content_type: str, body: bytes) -> str:
    """The URL's last path segment, with an extension the pipeline processes: the URL's own, or else
    the one its content type (or, for a PDF sent as application/octet-stream, its signature) says."""
    path = PurePosixPath(unquote(urlparse(url).path))
    stem = re.sub(r"[^\w.-]", "_", path.stem)[:100] or "document"
    if path.suffix.lower() in SUPPORTED_EXTENSIONS:
        return f"{stem}{path.suffix.lower()}"
    extension = _EXTENSION_BY_CONTENT_TYPE.get(content_type) or mimetypes.guess_extension(content_type or "") or ""
    if extension not in SUPPORTED_EXTENSIONS and body.startswith(b"%PDF-"):
        extension = ".pdf"
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedUrlContentError(f"{url} serves {content_type or 'an unknown format'}")
    return f"{stem}{extension}"


def content_hash(markdown: str) -> str:
    """SHA-256 of a page's extracted text, what a scheduled refresh compares to decide whether the
    page changed (#19). Of the extracted Markdown rather than the raw HTML, which changes for reasons
    the text doesn't show (scripts, tokens, ads); and lightly normalized - trailing spaces and runs of
    blank lines - so that layout noise alone doesn't trigger a full reprocessing."""
    lines = [line.rstrip() for line in markdown.strip().splitlines()]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
