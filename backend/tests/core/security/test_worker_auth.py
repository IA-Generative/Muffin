import pytest
from fastapi import HTTPException

from app.core.security import worker_auth


def test_rejects_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", "")
    with pytest.raises(HTTPException) as excinfo:
        worker_auth.require_worker_api_key(x_api_key="anything")
    assert excinfo.value.status_code == 401


def test_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", "correct-key")
    with pytest.raises(HTTPException):
        worker_auth.require_worker_api_key(x_api_key="wrong-key")


def test_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", "correct-key")
    worker_auth.require_worker_api_key(x_api_key="correct-key")
