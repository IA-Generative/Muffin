from unittest.mock import MagicMock

import pytest

from app import tasks
from app.owui_client import OwuiAccessGrant, OwuiKnowledge, OwuiUser


def _user(user_id: str, sub: str | None) -> OwuiUser:
    return OwuiUser(
        id=user_id, email=f"{user_id}@example.test", name=user_id, oauth={"oidc": {"sub": sub}} if sub else None
    )


def _grant(principal_type: str, principal_id: str, permission: str = "read") -> OwuiAccessGrant:
    return OwuiAccessGrant(principal_type=principal_type, principal_id=principal_id, permission=permission)


@pytest.fixture
def run(monkeypatch):
    """Runs the task for a knowledge base with these grants, and gives the body sent to the backend."""

    def _run(grants: list[OwuiAccessGrant], users: dict[str, OwuiUser]) -> tuple[dict, dict]:
        owui = MagicMock()
        owui.knowledge.return_value = OwuiKnowledge(
            id="kb1", user_id="owner", name="Procédures", description=None, access_grants=grants
        )
        owui.user.side_effect = users.__getitem__
        owui.embedding_model.return_value = "bge-multilingual-gemma2"
        backend = MagicMock()
        backend.sync_collection.return_value = {"id": "x", "created": True, "unknown_groups": []}
        monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
        monkeypatch.setattr(tasks, "backend_client", backend)
        result = tasks.sync_knowledge.run("kb1")
        source, external_id, body = backend.sync_collection.call_args.args
        assert (source, external_id) == ("owui", "kb1")
        return body, result

    return _run


def test_the_owner_is_their_keycloak_subject(run):
    body, _ = run([], {"owner": _user("owner", "kc-owner")})

    assert (body["owner_id"], body["name"], body["description"], body["public"]) == (
        "kc-owner",
        "Procédures",
        "",
        False,
    )
    assert body["embedding_model"] == "bge-multilingual-gemma2"


def test_an_owner_who_never_signed_in_through_keycloak_still_owns_it(run):
    body, _ = run([], {"owner": _user("owner", None)})

    assert body["owner_id"] == "owui:owner"


def test_the_read_grants_become_who_it_is_shared_with(run):
    users = {"owner": _user("owner", "kc-owner"), "u1": _user("u1", "kc-1"), "u2": _user("u2", None)}
    body, result = run([_grant("user", "u1"), _grant("user", "u2"), _grant("group", "g1"), _grant("user", "*")], users)

    assert body["public"] is True
    assert body["user_shares"] == [{"subject_id": "kc-1", "email": "u1@example.test"}]
    assert body["group_external_ids"] == ["g1"]
    assert result["readers_without_subject"] == 1


def test_a_write_grant_is_not_copied(run):
    body, result = run([_grant("user", "u1", "write"), _grant("group", "g1", "write")], {"owner": _user("owner", "kc")})

    assert (body["public"], body["user_shares"], body["group_external_ids"]) == (False, [], [])
    assert result["write_grants_ignored"] == 2
