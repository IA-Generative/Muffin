"""The scanned pages of a file, read by the OCR pods (OCR_ENGINE=layout) in place of liteparse's own Tesseract.

liteparse parses the file without OCR and says, for each page, whether one is needed. Those pages are sent to the pods
- their layout (app/ocr/ in worker/layout), then the text of its regions (worker/ocr) - a few at a time, and what comes
back is assembled into the page's markdown and positioned lines (app/ocr/assemble.py). A page that cannot be read -
a pod down or slow, a page with no region, one where nothing was read - falls back on liteparse and Tesseract, and the
file goes on: it fails only if that fails too.

The task that calls this waits for the pods (it polls their results, it does not block on one), looks whether it was
revoked between two polls, and revokes what it sent if it was (#326). Each page's temporary image is dropped when the
pages are read, whichever way it goes (#299: a replay overwrites what a previous run left)."""

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from pydantic import ValidationError

from app.config import settings
from app.ocr import assemble, pages, regions, routing
from app.ocr.contracts import PageLayout, PageText, RegionType
from app.task_revocation import TaskRevoked, raise_if_revoked

# The page's image at least this close to OCR_PAGE_DPI is read as it is, without rendering the page again.
_DPI_TOLERANCE = 0.95


def is_scanned(page: Any) -> bool:
    """Whether liteparse's reading of this page is not enough: it says the page was scanned or its text is garbled; or
    there is almost no native text and there are images on it (a blank page is no scan)."""
    stats = getattr(page, "complexity", None)
    if stats is None:
        # Without liteparse's signals: no text at all is taken for a scan.
        return len((page.text or "").strip()) < settings.OCR_SCANNED_MIN_CHARS
    if stats.is_garbled or "scanned" in stats.reasons:
        return True
    has_images = stats.full_page_image or stats.has_substantial_images or stats.image_block_count > 0
    return stats.text_length < settings.OCR_SCANNED_MIN_CHARS and has_images


@dataclass
class ReadPage:
    """A page the pods read: its markdown, its positioned lines, and the layout it was read with (#409)."""

    markdown: str
    items: list[Any]
    layout: PageLayout


@dataclass
class _Job:
    page: Any
    image_key: str
    stage: str = "layout"
    result: Any = None
    deadline: float = 0.0
    layout: PageLayout | None = None
    tables: set[int] = field(default_factory=set)


class ScannedPageReader:
    """Sends pages to the pods and gathers what they answer. `app` is the Celery app that sends; `clock` and `sleep`
    are how a test makes time go."""

    def __init__(
        self,
        app: Any = None,
        storage: Any = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if app is None:
            from app.celery_app import celery_app as app
        if storage is None:
            from app.storage import storage
        self._app, self._storage, self._clock, self._sleep = app, storage, clock, sleep

    def read(
        self, document_id: str, scanned: list[Any], images: dict[int, bytes]
    ) -> tuple[dict[int, ReadPage], list[int]]:
        """Returns the pages read - page number to what was read - and the numbers of those that were not."""
        waiting = list(scanned)
        active: dict[int, _Job] = {}
        read: dict[int, ReadPage] = {}
        failed: list[int] = []
        window = max(settings.OCR_PAGE_WINDOW, 1)
        try:
            while waiting or active:
                raise_if_revoked()
                while waiting and len(active) < window:
                    page = waiting.pop(0)
                    job = self._start(document_id, page, images.get(page.page_num))
                    if job is None:
                        failed.append(page.page_num)
                    else:
                        active[page.page_num] = job
                for number, job in list(active.items()):
                    outcome = self._poll(document_id, job)
                    if outcome is None:
                        continue
                    del active[number]
                    if isinstance(outcome, str):
                        logger.warning(f"Page {number} of {document_id} not read by the OCR pods: {outcome}")
                        failed.append(number)
                    else:
                        read[number] = outcome
                if active:
                    self._sleep(settings.OCR_POLL_SECONDS)
        except TaskRevoked:
            # What was sent is no longer wanted.
            for job in active.values():
                self._revoke(job)
            raise
        return read, failed

    def _start(self, document_id: str, page: Any, image: bytes | None) -> _Job | None:
        if not image:
            logger.warning(f"Page {page.page_num} of {document_id} has no image to send to the OCR pods")
            return None
        try:
            key = pages.put_page_image(self._storage, document_id, page.page_num, image)
            job = _Job(page=page, image_key=key)
            self._send_layout(document_id, job)
            return job
        except Exception as error:
            logger.warning(f"Page {page.page_num} of {document_id} could not be sent to the OCR pods: {error}")
            return None

    def _send_layout(self, document_id: str, job: _Job) -> None:
        job.result = self._app.send_task(routing.LAYOUT_PAGE_TASK, args=[document_id, job.page.page_num, job.image_key])
        job.deadline = self._clock() + settings.OCR_STAGE_TIMEOUT_SECONDS

    def _poll(self, document_id: str, job: _Job) -> ReadPage | str | None:
        """None: not yet. A string: why the page could not be read. Otherwise, the page read."""
        if self._clock() > job.deadline:
            self._revoke(job)
            return f"the {job.stage} step took more than {settings.OCR_STAGE_TIMEOUT_SECONDS} s"
        if not job.result.ready():
            return None
        if not job.result.successful():
            reason = f"the {job.stage} step failed: {job.result.result!r}"
            self._forget(job)
            return reason
        stage = job.stage
        try:
            if stage == "layout":
                return self._on_layout(document_id, job)
            return self._on_text(job)
        except (ValidationError, ValueError, TypeError) as error:
            return f"the {stage} step answered something unexpected: {error}"

    def _on_layout(self, document_id: str, job: _Job) -> None | str:
        layout = PageLayout.model_validate(job.result.result)
        self._forget(job)
        if not layout.regions:
            return "no region found on the page"
        job.layout = layout
        regions = []
        for region in layout.regions:
            if region.type is RegionType.TABLE and settings.OCR_READ_TABLES_AS_TEXT:
                job.tables.add(region.reading_order)
                region = region.model_copy(update={"type": RegionType.TEXT})
            regions.append(region.model_dump(mode="json"))
        job.stage = "ocr"
        job.result = self._app.send_task(
            routing.OCR_REGIONS_TASK, args=[document_id, job.page.page_num, job.image_key, regions]
        )
        job.deadline = self._clock() + settings.OCR_STAGE_TIMEOUT_SECONDS
        return None

    def _on_text(self, job: _Job) -> ReadPage | str:
        assert job.layout is not None
        text = PageText.model_validate(job.result.result)
        self._forget(job)
        markdown, items = assemble.assemble(job.layout, text, job.page.width, job.page.height, job.tables)
        if not markdown.strip():
            return "nothing was read on the page"
        return ReadPage(markdown, items, job.layout)

    def _revoke(self, job: _Job) -> None:
        try:
            if job.result is not None and not job.result.ready():
                job.result.revoke()
        except Exception as error:
            logger.debug(f"Could not revoke the {job.stage} task of page {job.page.page_num}: {error}")

    def _forget(self, job: _Job) -> None:
        try:
            job.result.forget()
        except Exception as error:
            logger.debug(f"Could not forget the {job.stage} result of page {job.page.page_num}: {error}")


def _dpi(screenshot: Any, page: Any) -> float:
    return screenshot.width / (page.width / 72) if page.width else 0.0


def _images_for(data: bytes, scanned: list[Any], result: Any) -> dict[int, bytes]:
    """The image of each scanned page at OCR_PAGE_DPI: the screenshot liteparse already made when it is sharp enough,
    the page rendered again when it is not."""
    from app import parsing

    shots = {shot.page_num: shot for shot in getattr(result, "screenshots", None) or []}
    images: dict[int, bytes] = {}
    missing: list[int] = []
    for page in scanned:
        shot = shots.get(page.page_num)
        if shot is not None and _dpi(shot, page) >= settings.OCR_PAGE_DPI * _DPI_TOLERANCE:
            images[page.page_num] = shot.image_bytes
        else:
            missing.append(page.page_num)
    if missing:
        images.update({number: png for number, (png, _, _) in parsing.render_pages(data, missing).items()})
    return images


def read_scanned_pages(document_id: str, data: bytes, result: Any, reader: ScannedPageReader | None = None) -> Any:
    """`result` (a liteparse ParseResult) with its scanned pages read by the OCR pods. Unchanged - and nothing is
    touched - when OCR_ENGINE is not "layout", or no page needs an OCR."""
    if settings.OCR_ENGINE != "layout":
        return result
    scanned = [page for page in result.pages if is_scanned(page)]
    if not scanned:
        return result
    from app import parsing
    from app.storage import storage

    numbers = [page.page_num for page in scanned]
    logger.info(
        f"{len(scanned)} of {len(result.pages)} page(s) need an OCR: read by the OCR pods, {pages_list(numbers)}"
    )
    started = time.monotonic()
    try:
        images = _images_for(data, scanned, result)
        read, failed = (reader or ScannedPageReader(storage=storage)).read(document_id, scanned, images)
    finally:
        try:
            pages.delete_pages_images(storage, document_id, numbers)
        except Exception as error:
            logger.warning(f"Could not drop the images sent to the OCR pods for {document_id}: {error}")

    replaced = {}
    for number, done in read.items():
        page = dataclasses.replace(
            next(page for page in scanned if page.page_num == number), text=done.markdown, text_items=done.items
        )
        # The page's layout (#409), kept by the backend with the page. A page that Tesseract read has none.
        page.layout_regions = regions.regions_of(done.layout)
        replaced[number] = page
    if failed:
        logger.warning(
            f"{len(failed)} page(s) of {document_id} fall back on liteparse's own OCR: {pages_list(sorted(failed))}"
        )
        for page in parsing.tesseract_pages(data, failed).pages:
            replaced[page.page_num] = page
    logger.info(f"OCR pods: {len(read)} page(s) read, {len(failed)} fell back, in {time.monotonic() - started:.0f} s")
    return dataclasses.replace(result, pages=[replaced.get(page.page_num, page) for page in result.pages])


def pages_list(numbers: list[int]) -> str:
    """The pages as a short list for a log line: "1-3, 7"."""
    from app.parsing import _page_list

    return _page_list(numbers).replace(",", ", ")
