from unittest.mock import MagicMock

import pytest

from app import tasks
from app.owui_client import OwuiGroup, OwuiUser


def _user(n: int, oauth=None) -> OwuiUser:
    return OwuiUser(id=f"o{n}", email=f"u{n}@example.test", name=f"User {n}", oauth=oauth)


def test_a_user_is_known_by_the_subject_of_their_identity_provider():
    assert _user(1, {"oidc": {"sub": "kc-1"}}).keycloak_sub == "kc-1"
    assert _user(2, {"oidc": {"email": "x"}}).keycloak_sub is None
    assert _user(3).keycloak_sub is None


@pytest.fixture
def owui(monkeypatch):
    client = MagicMock()
    client.group.return_value = OwuiGroup(id="g1", name="Équipe A", description=None)
    client.group_members.return_value = iter(
        [_user(1, {"oidc": {"sub": "kc-2"}}), _user(2, {"oidc": {"sub": "kc-1"}}), _user(3)]
    )
    monkeypatch.setattr(tasks, "OwuiClient", lambda: client)
    return client


def test_the_group_is_sent_with_the_subjects_of_its_members(owui, monkeypatch):
    backend = MagicMock()
    backend.sync_group.return_value = {"id": "x", "created": True, "members_added": 2, "members_removed": 0}
    monkeypatch.setattr(tasks, "backend_client", backend)

    result = tasks.sync_group.run("g1")

    backend.sync_group.assert_called_once_with("owui", "g1", "Équipe A", "", ["kc-1", "kc-2"])
    assert result["members_added"] == 2
    assert result["members_without_subject"] == 1
