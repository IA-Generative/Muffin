"""The worker's Celery tasks - the only place they are declared.

Each task is a thin entrypoint: it carries the Celery wiring (the registered name the
backend dispatches to, see backend/app/core/tasks.py) and delegates to the plain
function of the same name in app/evaluation.py or app/discussion.py, where the
behaviour and its tests live. Neither task registers a self.request.id Task row,
unlike worker/document_process's spawned tasks: each is a single task with no
children, and the backend already creates its Task row itself right after
dispatching it (see EvaluationService.trigger / ConversationService.
trigger_discussion_score - it already knows the user at that point, no round trip
needed).
"""

from app import discussion, evaluation
from app.celery_app import celery_app


@celery_app.task(name="app.tasks.run_evaluation", bind=True)
def run_evaluation(self, collection_id: str, k: int | None = None, validated_only: bool = False) -> None:
    """Celery entrypoint for evaluation.run_evaluation - see there for the behaviour."""
    evaluation.run_evaluation(collection_id, k, validated_only)


@celery_app.task(name="app.tasks.score_discussion", bind=True)
def score_discussion(self, conversation_id: str, model: str | None = None) -> None:
    """Celery entrypoint for discussion.score_discussion - see there for the behaviour."""
    discussion.score_discussion(conversation_id, model)
