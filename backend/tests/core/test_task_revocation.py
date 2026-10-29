"""What revoking a task does to the task itself, in Redis (the test database's)."""

from unittest.mock import patch

from celery.result import AsyncResult

from app.core import tasks


def _task_status(task_id: str) -> str:
    return AsyncResult(task_id, app=tasks._celery_app).status


def test_a_revoked_task_leaves_a_flag_for_the_workers_and_says_so_in_its_status():
    task_id = "revoked-by-the-test-1"

    with patch.object(tasks._celery_app.control, "revoke") as broadcast:
        tasks.revoke_tasks([task_id])

    assert tasks._celery_app.backend.client.exists(tasks.REVOKED_KEY.format(task_id=task_id))
    assert _task_status(task_id) == "REVOKED"
    broadcast.assert_called_once_with([task_id], terminate=True)


def test_the_flag_expires_with_the_result():
    task_id = "revoked-by-the-test-2"
    with patch.object(tasks._celery_app.control, "revoke"):
        tasks.revoke_tasks([task_id])

    ttl = tasks._celery_app.backend.client.ttl(tasks.REVOKED_KEY.format(task_id=task_id))

    assert 0 < ttl <= tasks._celery_app.conf.result_expires


def test_nothing_to_revoke_sends_nothing():
    with patch.object(tasks._celery_app.control, "revoke") as broadcast:
        tasks.revoke_tasks([])

    broadcast.assert_not_called()


def test_only_the_tasks_still_to_run_or_running_are_active():
    from app.models.task import Task, TaskStatus

    active = {TaskStatus.PENDING, TaskStatus.STARTED}
    for status in TaskStatus:
        assert Task(status=status).is_active is (status in active)
