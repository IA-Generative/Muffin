from app.celery_app import celery_app
from app.config import settings
from app.tasks import sync_owui


def test_the_worker_has_its_own_queue():
    assert settings.CELERY_QUEUE_NAME == "owui_sync"
    assert celery_app.conf.task_default_queue == "owui_sync"
    assert celery_app.amqp.router.route({}, "app.tasks.sync_owui")["queue"].name == "owui_sync"


def test_sync_owui_is_registered():
    assert "app.tasks.sync_owui" in celery_app.tasks
    assert sync_owui.run() == {"status": "nothing_to_do"}
