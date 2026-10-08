from typing import Any

from loguru import logger

from app.celery_app import celery_app
from app.contract import EditJobInput, EditJobResult
from app.storage import storage
from app.task_logging import capture_task_logs

_MEDIA_TYPES = {"odt": "application/vnd.oasis.opendocument.text", "md": "text/markdown; charset=utf-8"}


def draft_key(document_id: str, job_id: str, format_: str) -> str:
    """Where a job's draft lives. Under drafts/ rather than documents/: a draft is a temporary
    object (cleaned up on refusal or expiry, #169), never part of a collection's own files."""
    return f"drafts/{document_id}/{job_id}.{format_}"


@celery_app.task(name="app.tasks.edit_document", bind=True)
def edit_document(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Produces a draft of a living document from a prompt. Stateless: reads its starting point
    from RustFS, writes the draft back, returns the result and stops - the validate / adjust /
    refuse loop lives in the backend, not here.

    Skeleton (#167): the draft is an unmodified copy of its starting point (`edited` stays False)
    - the LangGraph agent that actually applies edits is #168, the PDF preview #169. It already
    exercises the whole path (queue, contract, RustFS read/write, task logs)."""
    with capture_task_logs(self.request.id):
        job = EditJobInput.model_validate(payload)
        start_key = job.previous_draft_key or job.source_storage_key
        logger.info(f"Edit job for document {job.document_id} (revision {job.base_revision}) from {start_key}")

        data = storage.get_object(start_key)
        key = draft_key(job.document_id, self.request.id, job.format)
        storage.put_object(key, data, content_type=_MEDIA_TYPES[job.format])
        logger.info(f"Wrote draft {key} ({len(data)} bytes), no edit applied yet")

        return EditJobResult(draft_storage_key=key).model_dump()
