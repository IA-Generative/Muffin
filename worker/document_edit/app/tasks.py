from typing import Any

from loguru import logger

from app.agent import EditFailedError, run_edit_agent
from app.backend_client import backend_client
from app.celery_app import celery_app
from app.config import settings
from app.contract import EditJobInput, EditJobResult
from app.storage import storage
from app.task_logging import capture_task_logs

_MEDIA_TYPES = {"odt": "application/vnd.oasis.opendocument.text", "md": "text/markdown; charset=utf-8"}


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


@celery_app.task(name="app.tasks.edit_document", bind=True)
def edit_document(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Produces a draft of a living document from a prompt. Stateless: reads its starting point
    from RustFS, runs the editing agent on it, writes the draft back, returns the result and
    stops - the validate / adjust / refuse loop lives in the backend, not here.

    The source file is never modified. When the agent finds nothing to change (or declines), the
    draft is an unchanged copy and `edited` is False, with its explanation in operations_summary.
    When it can't produce an applicable edit at all, the task fails (EditFailedError) and its
    message is in the task's logs. The PDF preview is #169."""
    with capture_task_logs(self.request.id):
        job = EditJobInput.model_validate(payload)
        start_key = job.previous_draft_key or job.source_storage_key
        logger.info(f"Edit job for document {job.document_id} (revision {job.base_revision}) from {start_key}")

        source = storage.get_object(start_key)
        try:
            outcome = run_edit_agent(
                source,
                job.format,
                job.prompt,
                _llm(),
                max_attempts=settings.EDIT_MAX_ATTEMPTS,
                max_outline_chars=settings.EDIT_MAX_OUTLINE_CHARS,
            )
        except EditFailedError as failure:
            logger.error(failure.message)
            raise

        key = draft_key(job.document_id, self.request.id, job.format)
        storage.put_object(key, outcome.data, content_type=_MEDIA_TYPES[job.format])
        logger.info(f"Wrote draft {key} ({len(outcome.data)} bytes), edited={outcome.edited}")

        summary = "\n".join(f"- {line}" for line in outcome.summary) if outcome.edited else outcome.message
        return EditJobResult(
            draft_storage_key=key,
            operations_summary=summary,
            pending_images=outcome.pending_images,
            edited=outcome.edited,
        ).model_dump()
