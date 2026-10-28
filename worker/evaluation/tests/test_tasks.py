from app.celery_app import celery_app


def test_the_worker_declares_both_tasks_under_the_backend_names():
    # The names are the contract with the backend (backend/app/core/tasks.py's
    # RUN_EVALUATION_TASK / SCORE_DISCUSSION_TASK): a rename here without the backend
    # would leave dispatched tasks unrouted. The behaviour itself is tested against the
    # plain functions in test_evaluation.py / test_discussion.py.
    assert "app.tasks.run_evaluation" in celery_app.tasks
    assert "app.tasks.score_discussion" in celery_app.tasks
