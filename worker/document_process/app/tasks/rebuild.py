"""Blue/green rebuild of a collection's search index (#12).

The backend keeps the state in PostgreSQL and decides what the new index still lacks: this task only
loops "ask for the next points, embed them, hand the vectors back" until nothing is missing, then
asks for the swap. Nothing is kept here, so a task killed halfway (or redelivered after a crash)
simply picks up with whatever the next plan says is left.

It runs on its own queue (INDEX_REBUILD_QUEUE on the backend), so a large rebuild never holds up the
ingestion of new documents.
"""

import time

from loguru import logger

from app.celery_app import celery_app
from app.tasks import _shared

# Texts per embedding call: the hub accepts large batches, but a rebuild's vectors are stored per
# batch, so a smaller one loses less when the task is interrupted.
EMBED_BATCH = 64
# A safety net, not a limit: each pass either stores vectors or swaps, so this only stops a rebuild
# that never converges (points the backend keeps refusing).
MAX_PASSES = 10_000
# A hub or backend hiccup shouldn't fail a rebuild that may have been running for hours.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


def _embed_and_store(rebuild_id: str, model: str, batch: list[dict]) -> None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            embeddings = _shared.backend_client.embed_batch(model, [point["text"] for point in batch])
            _shared.backend_client.submit_rebuild_vectors(
                rebuild_id,
                model,
                [
                    {"id": point["id"], "kind": point["kind"], "text": point["text"], "embedding": embedding}
                    for point, embedding in zip(batch, embeddings, strict=True)
                ],
            )
            return
        except Exception:
            if attempt == ATTEMPTS:
                raise
            logger.warning(f"Index rebuild {rebuild_id}: batch failed (attempt {attempt}), retrying")
            time.sleep(RETRY_DELAY_SECONDS * attempt)


# The app-wide 5 minutes (a hung parser) would kill a long rebuild; the work is resumable anyway,
# so this only bounds a task stuck for good.
@celery_app.task(name="app.tasks.rebuild_index", time_limit=24 * 3600)
def rebuild_index(rebuild_id: str) -> str:
    backend = _shared.backend_client
    try:
        for _ in range(MAX_PASSES):
            plan = backend.get_rebuild_plan(rebuild_id)
            if plan["status"] not in ("building", "swapped", "rolled_back"):
                return plan["status"]
            if not plan["points"]:
                if plan["status"] != "building":
                    return plan["status"]
                # Everything is there: swap, or go on if a document was added since the plan.
                backend.swap_rebuild(rebuild_id)
                continue
            points = plan["points"]
            for start in range(0, len(points), EMBED_BATCH):
                _embed_and_store(rebuild_id, plan["model"], points[start : start + EMBED_BATCH])
            logger.info(f"Index rebuild {rebuild_id}: {len(points)} vector(s) made, {plan['remaining']} to go")
        raise RuntimeError(f"The rebuild did not converge after {MAX_PASSES} passes")
    except Exception as error:
        logger.exception(f"Index rebuild {rebuild_id} failed")
        backend.fail_rebuild(rebuild_id, str(error))
        raise
