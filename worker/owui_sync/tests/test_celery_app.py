from app.celery_app import celery_app
from app.config import settings


def test_the_worker_has_its_own_queue():
    assert settings.CELERY_QUEUE_NAME == "owui_sync"
    assert celery_app.conf.task_default_queue == "owui_sync"
    assert celery_app.amqp.router.route({}, "app.tasks.sync_owui")["queue"].name == "owui_sync"


def test_the_tasks_of_a_synchronisation_are_registered():
    for name in (
        "sync_owui",
        "sync_group",
        "sync_knowledge",
        "sync_knowledge_file",
        "sync_knowledge_bases",
        "sync_files",
        "finish_sync",
    ):
        assert f"app.tasks.{name}" in celery_app.tasks
