from typing import Any

from loguru import logger

from app.agent import EditFailedError, run_edit_agent
from app.backend_client import backend_client
from app.celery_app import celery_app
from app.config import settings
from app.contract import EditJobInput, EditJobResult, InsertImagesInput
from app.edit_types import OperationError
from app.odt_editor import ImageData, insert_images
from app.preview import PreviewError, convert_to_pdf
from app.storage import storage
from app.task_logging import capture_task_logs

_MEDIA_TYPES = {"odt": "application/vnd.oasis.opendocument.text", "md": "text/markdown; charset=utf-8"}
_INTERNAL_ERROR = "L'édition a échoué (erreur interne)."


def draft_key(document_id: str, job_id: str, format_: str) -> str:
    """Where a job's draft lives. Under drafts/ rather than documents/: a draft is a temporary
    object (cleaned up on refusal or expiry, #169), never part of a collection's own files."""
    return f"drafts/{document_id}/{job_id}.{format_}"


def _llm():
    """The chat function the agent plans with: the configured model, else the hub's default."""
    model = settings.EDIT_LLM_MODEL or backend_client.get_default_chat_model()
    if not model:
        raise EditFailedError("Aucun modèle de chat n'est configuré pour modifier le document.")

    def chat(messages: list[dict[str, str]]) -> str:
        return backend_client.llm_chat(model, messages, max_tokens=settings.EDIT_MAX_TOKENS)

    return chat


def _store_draft(document_id: str, job_id: str, format_: str, data: bytes, *, preview: bool) -> tuple[str, str | None]:
    """Writes the draft and, for an ODT that was really edited, the PDF the user will validate it
    from. Returns their keys."""
    key = draft_key(document_id, job_id, format_)
    storage.put_object(key, data, content_type=_MEDIA_TYPES[format_])
    if format_ != "odt" or not preview:
        return key, None
    try:
        pdf = convert_to_pdf(data)
    except PreviewError as error:
        raise EditFailedError(f"Le brouillon est prêt mais son aperçu n'a pas pu être généré : {error}.") from error
    pdf_key = draft_key(document_id, job_id, "pdf")
    storage.put_object(pdf_key, pdf, content_type="application/pdf")
    return key, pdf_key


def _report_failure(job_id: str, message: str) -> None:
    """Best-effort: the task is failing anyway, and the backend also notices a draft whose job never
    reports (it expires with its lock)."""
    try:
        backend_client.report_draft_failure(job_id, message)
    except Exception:
        logger.exception(f"Failed to report the failure of job {job_id} to the backend")


def _run(job_id: str, kind: str, work) -> dict[str, Any]:
    try:
        result: EditJobResult = work()
    except Exception as error:
        message = error.message if isinstance(error, EditFailedError) else _INTERNAL_ERROR
        logger.error(message)
        _report_failure(job_id, message)
        raise
    payload = {"kind": kind, **result.model_dump()}
    backend_client.report_draft_result(job_id, payload)
    return result.model_dump()


@celery_app.task(name="app.tasks.edit_document", bind=True)
def edit_document(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Produces a draft of a living document from a prompt. Stateless: reads its starting point
    from RustFS, runs the editing agent on it, writes the draft (and, for an ODT, its PDF preview)
    back, reports the result to the backend and stops - the validate / adjust / refuse loop lives in
    the backend, not here.

    The source file is never modified. When the agent finds nothing to change (or declines), the
    draft is an unchanged copy and `edited` is False, with its explanation in operations_summary and
    no preview. When it can't produce an applicable edit at all, the task fails (EditFailedError),
    the backend is told why, and the message is in the task's logs."""
    with capture_task_logs(self.request.id):

        def work() -> EditJobResult:
            job = EditJobInput.model_validate(payload)
            start_key = job.previous_draft_key or job.source_storage_key
            logger.info(f"Edit job for document {job.document_id} (revision {job.base_revision}) from {start_key}")

            outcome = run_edit_agent(
                storage.get_object(start_key),
                job.format,
                job.prompt,
                _llm(),
                max_attempts=settings.EDIT_MAX_ATTEMPTS,
                max_outline_chars=settings.EDIT_MAX_OUTLINE_CHARS,
            )
            # An unchanged copy needs no preview: there is nothing to look at, only a message.
            key, pdf_key = _store_draft(
                job.document_id, self.request.id, job.format, outcome.data, preview=outcome.edited
            )
            logger.info(f"Wrote draft {key} ({len(outcome.data)} bytes), edited={outcome.edited}, preview={pdf_key}")

            summary = "\n".join(f"- {line}" for line in outcome.summary) if outcome.edited else outcome.message
            return EditJobResult(
                draft_storage_key=key,
                preview_pdf_key=pdf_key,
                operations_summary=summary,
                pending_images=outcome.pending_images,
                edited=outcome.edited,
            )

        return _run(self.request.id, "edit", work)


@celery_app.task(name="app.tasks.insert_images", bind=True)
def insert_images_task(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Adds the images the user uploaded to an ODT draft and renders a fresh preview - a
    deterministic step, no model. The draft it started from is left as it was; the result points at
    the new files."""
    with capture_task_logs(self.request.id):

        def work() -> EditJobResult:
            job = InsertImagesInput.model_validate(payload)
            logger.info(f"Inserting {len(job.images)} image(s) into the draft of document {job.document_id}")
            images = [
                ImageData(
                    id=image.id,
                    description=image.description,
                    content=storage.get_object(image.storage_key),
                    section=image.section,
                    after_paragraph=image.after_paragraph,
                )
                for image in job.images
            ]
            try:
                result = insert_images(storage.get_object(job.draft_storage_key), images)
            except OperationError as error:
                raise EditFailedError(error.message) from error
            key, pdf_key = _store_draft(job.document_id, self.request.id, "odt", result.data, preview=True)
            return EditJobResult(
                draft_storage_key=key,
                preview_pdf_key=pdf_key,
                operations_summary="\n".join(f"- {line}" for line in result.summary),
                edited=True,
            )

        return _run(self.request.id, "images", work)
