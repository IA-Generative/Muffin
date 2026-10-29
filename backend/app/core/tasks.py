from celery import Celery

from app.config import RedisSettings

_redis_settings = RedisSettings()
_celery_app = Celery(
    "muffin_backend_producer",
    broker=_redis_settings.REDIS_URL,
    backend=_redis_settings.REDIS_URL,
)
# Celery's own default (1 day) would make a task's status silently fall back
# to PENDING once its result key expires, well before anyone looking at a
# task history would expect it to disappear.
_celery_app.conf.result_expires = 60 * 60 * 24 * 7

# worker/document_process runs as three pods (#291), one per kind of work, each consuming its own
# queues. Must match that worker's app/config.py and app/celery_app.py exactly - the backend only
# produces these tasks, it never imports the worker's code (separate service, separate deploy).
# Extraction: OCR, parsing, fetching a URL (CPU).
DOCUMENT_EXTRACTION_QUEUE = "document_extraction"
PROCESS_DOCUMENT_TASK = "app.tasks.process_document"
# Fetching a URL document's page again, to reprocess it if it changed (#19) - on demand here.
REFRESH_URL_DOCUMENT_TASK = "app.tasks.refresh_url_document"
# Celery's Redis priorities run from 0 (the highest, what a message without one gets) to 9. A
# document a ZIP import created is sent with the lowest: Redis keeps it in a list of its own, which
# the worker only reads once the normal one is empty - so a file someone just dropped never waits
# behind the 2000 documents of an archive.
BULK_PRIORITY = 9

# Enrichment: embeddings and LLM calls (network), on a pool of threads. Recomputing a parent
# collection's description from its own documents and its sub-collections' descriptions (#218).
# Always sent with a countdown, see app/services/description_rollup_service.py.
DOCUMENT_ENRICHMENT_QUEUE = "document_enrichment"
ROLLUP_COLLECTION_DESCRIPTION_TASK = "app.tasks.rollup_collection_description"

# Long I/O, on the index rebuilds' pod: turning an uploaded ZIP into a collection and its
# sub-collections (#223) - minutes for a large archive, which must hold up no extraction slot.
DOCUMENT_IMPORT_QUEUE = "document_import"
IMPORT_ZIP_TASK = "app.tasks.import_zip"

# Same reasoning, for the separate worker/agent_execution service - a
# distinct queue so scaling/deploying one worker never affects the other,
# even though both are produced from this same Celery app instance.
AGENT_EXECUTION_QUEUE = "agent_execution"
RUN_AGENT_TASK = "app.tasks.run_agent"
RESUME_AGENT_TASK = "app.tasks.resume_agent"

# Same reasoning again, for worker/evaluation (see #11) - a retrieval evaluation replays every
# validated QA pair of a collection through search + generation, potentially long and LLM-heavy,
# so it gets its own queue rather than competing with document ingestion or agent_execution.
EVALUATION_QUEUE = "evaluation"
RUN_EVALUATION_TASK = "app.tasks.run_evaluation"
# A second task type on the same worker/evaluation service and queue (see #31) - one LLM judgment
# call over a conversation transcript, nowhere near the batch-of-many-searches cost of
# run_evaluation, so it doesn't warrant its own dedicated service/Dockerfile/queue.
SCORE_DISCUSSION_TASK = "app.tasks.score_discussion"

# Tasks with no enforced runtime limit: a healthy one can legitimately outlive the reaper's
# cutoff, so age alone cannot tell it from a lost one. The reaper leaves them alone (see
# TaskRepository.reap_stuck) - a dead one stays STARTED, but the user can still revoke it.
UNBOUNDED_TASK_NAMES = frozenset({RUN_EVALUATION_TASK, SCORE_DISCUSSION_TASK})

# And again for worker/document_edit (#167) - an edit job runs an LLM and a LibreOffice
# conversion, so it gets its own queue rather than competing with the others.
DOCUMENT_EDIT_QUEUE = "document_edit"
# Rebuilding a collection's search index with a new embedding model (#12): its own queue and pod
# (with the ZIP imports), so a large rebuild never holds up the ingestion of new documents.
INDEX_REBUILD_QUEUE = "index_rebuild"
REBUILD_INDEX_TASK = "app.tasks.rebuild_index"
EDIT_DOCUMENT_TASK = "app.tasks.edit_document"
# The synchronisation with Open WebUI (#453): its own worker and queue, which lists and copies a whole Open WebUI.
OWUI_SYNC_QUEUE = "owui_sync"
SYNC_OWUI_TASK = "app.tasks.sync_owui"
# Same worker and queue: putting a user's uploaded images into an ODT draft (#169).
INSERT_IMAGES_TASK = "app.tasks.insert_images"
# Same worker and queue: rendering the PDF previews of a file the user picked to replace a document.
RENDER_UPLOAD_TASK = "app.tasks.render_upload"


def enqueue_process_document(document_id: str, *, bulk: bool = False, task_id: str | None = None) -> str:
    """Returns the Celery task id, so the caller can record it (see
    app/models/task.py) for later status lookups and revocation. `bulk`: one of the many documents
    of a ZIP import, processed after any other waiting. `task_id`: preallocated by the caller when
    it records the Task row before publishing, so the worker's first status report finds it."""
    options = {"priority": BULK_PRIORITY} if bulk else {}
    result = _celery_app.send_task(
        PROCESS_DOCUMENT_TASK, args=[document_id], queue=DOCUMENT_EXTRACTION_QUEUE, task_id=task_id, **options
    )
    return result.id


def enqueue_refresh_url_document(document_id: str, task_id: str | None = None) -> str:
    """A URL document's page fetched now rather than at its next scheduled check. Returns the Celery
    task id, as enqueue_process_document does. `task_id`: preallocated by the caller when it records
    the Task row before publishing."""
    result = _celery_app.send_task(
        REFRESH_URL_DOCUMENT_TASK, args=[document_id], queue=DOCUMENT_EXTRACTION_QUEUE, task_id=task_id
    )
    return result.id


def enqueue_rollup_collection_description(collection_id: str, countdown: int, task_id: str | None = None) -> str:
    """Returns the Celery task id. `countdown` delays the run so that every change to the
    sub-collections within that window is picked up by this single run. `task_id`: preallocated by
    the caller when it records the Task row before publishing."""
    result = _celery_app.send_task(
        ROLLUP_COLLECTION_DESCRIPTION_TASK,
        args=[collection_id],
        queue=DOCUMENT_ENRICHMENT_QUEUE,
        countdown=countdown,
        task_id=task_id,
    )
    return result.id


def enqueue_import_zip(import_id: str, task_id: str | None = None) -> str:
    """Returns the Celery task id, recorded as a collection-scoped Task row. `task_id`: preallocated
    by the caller when it records the Task row before publishing."""
    result = _celery_app.send_task(IMPORT_ZIP_TASK, args=[import_id], queue=DOCUMENT_IMPORT_QUEUE, task_id=task_id)
    return result.id


def enqueue_run_agent(run_id: str) -> str:
    """Returns the Celery task id, recorded on the Run row itself (see
    app/models/run.py) rather than a separate Task row - a run already has
    the id, and it's 1:1 with its own dispatch (no parent/children)."""
    result = _celery_app.send_task(RUN_AGENT_TASK, args=[run_id], queue=AGENT_EXECUTION_QUEUE)
    return result.id


def enqueue_resume_agent(run_id: str, answer: str) -> str:
    """Continues a run paused on request_clarification's interrupt() (§31) - a distinct task
    name/args from enqueue_run_agent rather than overloading it, since resuming re-enters the
    same checkpointed graph execution (Command(resume=...)) instead of starting a fresh one.
    """
    result = _celery_app.send_task(RESUME_AGENT_TASK, args=[run_id, answer], queue=AGENT_EXECUTION_QUEUE)
    return result.id


def enqueue_run_evaluation(collection_id: str, k: int, validated_only: bool = False, task_id: str | None = None) -> str:
    """Returns the Celery task id, recorded as a collection-scoped Task row (see
    app/routers/internal_tasks.py) rather than on a pre-created EvaluationRun - the model has no
    in-progress state, the run row only ever exists once the worker posts a fully computed one.
    `task_id`: preallocated by the caller when it records the Task row before publishing.
    """
    result = _celery_app.send_task(
        RUN_EVALUATION_TASK,
        args=[collection_id, k, validated_only],
        queue=EVALUATION_QUEUE,
        task_id=task_id,
    )
    return result.id


def enqueue_score_discussion(conversation_id: str, model: str | None = None, task_id: str | None = None) -> str:
    """Returns the Celery task id, recorded as a conversation-scoped Task row (see
    app/routers/internal_tasks.py) - same reasoning as enqueue_run_evaluation, the DiscussionScore
    row only ever exists once the worker posts a fully computed one.

    When `model` is None, the worker picks the hub's default chat model. When set, the worker
    uses that specific model - the (conversation, content_hash, model) unique index means
    re-scoring the same transcript with a different model creates a new score row instead of
    being a no-op. `task_id`: preallocated by the caller when it records the Task row before
    publishing."""
    args: list = [conversation_id] if model is None else [conversation_id, model]
    result = _celery_app.send_task(SCORE_DISCUSSION_TASK, args=args, queue=EVALUATION_QUEUE, task_id=task_id)
    return result.id


def enqueue_edit_document(payload: dict, task_id: str | None = None) -> str:
    """Returns the Celery task id, recorded as a document-scoped Task row (see
    app/routers/internal_tasks.py). `payload` is worker/document_edit's EditJobInput
    (app/contract.py there) - a plain dict, not a shared class, since the backend never imports a
    worker's code. The worker is stateless: it writes a draft to RustFS and returns its result,
    the validate/adjust/refuse loop lives in the backend."""
    result = _celery_app.send_task(EDIT_DOCUMENT_TASK, args=[payload], queue=DOCUMENT_EDIT_QUEUE, task_id=task_id)
    return result.id


def enqueue_sync_owui() -> str:
    """Starts a synchronisation with Open WebUI now, on top of the periodic one. Returns the Celery task id."""
    return _celery_app.send_task(SYNC_OWUI_TASK, queue=OWUI_SYNC_QUEUE).id


def enqueue_insert_images(payload: dict, task_id: str | None = None) -> str:
    """`payload` is worker/document_edit's InsertImagesInput. Pass a `task_id` chosen (and stored)
    beforehand when the worker reports back by it: it avoids the race where the worker finishes
    before the caller has recorded the id Celery would have generated."""
    result = _celery_app.send_task(INSERT_IMAGES_TASK, args=[payload], queue=DOCUMENT_EDIT_QUEUE, task_id=task_id)
    return result.id


def enqueue_render_upload(payload: dict, task_id: str | None = None) -> str:
    """`payload` is worker/document_edit's RenderUploadInput. Same `task_id` convention as
    enqueue_insert_images."""
    result = _celery_app.send_task(RENDER_UPLOAD_TASK, args=[payload], queue=DOCUMENT_EDIT_QUEUE, task_id=task_id)
    return result.id


def enqueue_rebuild_index(rebuild_id: str, task_id: str | None = None) -> str:
    result = _celery_app.send_task(REBUILD_INDEX_TASK, args=[rebuild_id], queue=INDEX_REBUILD_QUEUE, task_id=task_id)
    return result.id


# The flag a revoked task leaves in Redis, which every worker looks at when a task starts (see
# app/task_revocation.py in each worker - the key must be the same). Celery's own revoke is a broadcast
# to the workers up at that moment, kept in their memory: a task revoked while it waits in the queue
# runs all the same on a pod that starts afterwards (a deploy, a scale-up), and one whose worker died
# runs again, revoked or not, when Redis hands it out again - after the visibility timeout, hours.
REVOKED_KEY = "muffin:revoked:{task_id}"


def revoke_tasks(celery_task_ids: list[str]) -> None:
    """Revokes tasks for good, however far each is:
    - a flag in Redis, for the workers that start the task later or run it again;
    - REVOKED in the result backend, so that the status says so now, with no worker alive to say it;
    - Celery's broadcast, with terminate, for the workers that have it now: a running task is killed
      (only in a prefork pool - one of threads stops it itself, see the workers' task_revocation.py)."""
    if not celery_task_ids:
        return
    client = _celery_app.backend.client
    for task_id in celery_task_ids:
        client.set(REVOKED_KEY.format(task_id=task_id), 1, ex=_celery_app.conf.result_expires)
        _celery_app.backend.mark_as_revoked(task_id, reason="revoked by the user")
    _celery_app.control.revoke(celery_task_ids, terminate=True)
