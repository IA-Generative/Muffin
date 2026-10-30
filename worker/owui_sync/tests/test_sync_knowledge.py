from unittest.mock import MagicMock

import pytest

from app import tasks
from app.owui_client import OwuiAccessGrant, OwuiKnowledge, OwuiUser
from app.owui_vectors import CollectionInfo


def _user(user_id: str, sub: str | None) -> OwuiUser:
    return OwuiUser(
        id=user_id, email=f"{user_id}@example.test", name=user_id, oauth={"oidc": {"sub": sub}} if sub else None
    )


def _grant(principal_type: str, principal_id: str, permission: str = "read") -> OwuiAccessGrant:
    return OwuiAccessGrant(principal_type=principal_type, principal_id=principal_id, permission=permission)


@pytest.fixture
def vectors(monkeypatch):
    """What Qdrant says of the knowledge base's collection: by default, vectors of the right model and length."""
    fake = MagicMock()
    fake.inspect.return_value = CollectionInfo(True, 3, frozenset({"bge-multilingual-gemma2"}))
    monkeypatch.setattr(tasks, "OwuiVectors", lambda: fake)
    return fake


@pytest.fixture
def backend(monkeypatch):
    fake = MagicMock()
    fake.sync_collection.return_value = {"id": "x", "created": True, "unknown_groups": []}
    fake.embed.return_value = [0.0, 0.0, 0.0]  # a model whose vectors are 3 long
    tasks._MODEL_DIMENSIONS.clear()
    monkeypatch.setattr(tasks, "backend_client", fake)
    return fake


@pytest.fixture
def run(monkeypatch, vectors, backend):
    """Runs the task for a knowledge base with these grants, and gives the body sent to the backend."""

    def _run(grants: list[OwuiAccessGrant], users: dict[str, OwuiUser], files: list[dict] | None = None):
        owui = MagicMock()
        owui.knowledge.return_value = OwuiKnowledge(
            id="kb1", user_id="owner", name="Procédures", description=None, access_grants=grants, files=files or []
        )
        owui.user.side_effect = users.__getitem__
        owui.embedding_model.return_value = "bge-multilingual-gemma2"
        monkeypatch.setattr(tasks, "OwuiClient", lambda: owui)
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
    assert body["user_shares"] == [{"subject_id": "kc-1", "email": "u1@example.test", "permission": "read"}]
    assert body["group_external_ids"] == ["g1"]
    assert body["write_group_external_ids"] == []
    assert result["readers_without_subject"] == 1


def test_a_reader_who_also_writes_in_open_webui_writes_in_muffin(run):
    users = {"owner": _user("owner", "kc-owner"), "u1": _user("u1", "kc-1"), "u2": _user("u2", "kc-2")}
    body, _ = run(
        [
            _grant("user", "u1"),
            _grant("user", "u1", "write"),
            _grant("user", "u2"),
            _grant("group", "g1"),
            _grant("group", "g1", "write"),
            _grant("group", "g2"),
        ],
        users,
    )

    assert {share["subject_id"]: share["permission"] for share in body["user_shares"]} == {
        "kc-1": "write",
        "kc-2": "read",
    }
    assert body["group_external_ids"] == ["g1", "g2"]
    assert body["write_group_external_ids"] == ["g1"]


def test_muffin_is_never_more_generous_than_open_webui(run):
    body, result = run(
        [_grant("user", "u1", "write"), _grant("group", "g1", "write"), _grant("user", "*", "write")],
        {"owner": _user("owner", "kc")},
    )

    assert (body["public"], body["user_shares"], body["group_external_ids"]) == (False, [], [])
    assert body["write_group_external_ids"] == []
    assert result["write_grants_ignored"] == 3


def test_nothing_is_reported_when_the_vectors_are_of_the_model_open_webui_is_set_to(run):
    _, result = run([], {"owner": _user("owner", "kc")})

    assert result["vector_problems"] == []
    assert result["knowledge_id"] == "kb1"


def test_chunks_made_with_another_model_are_reported_and_the_copy_goes_on(run, vectors, backend):
    vectors.inspect.return_value = CollectionInfo(True, 3, frozenset({"old-model", "bge-multilingual-gemma2"}))

    _, result = run([], {"owner": _user("owner", "kc")})

    assert result["vector_problems"] == [
        "chunks made with old-model, while Open WebUI is set to bge-multilingual-gemma2"
    ]
    backend.sync_collection.assert_called_once()


def test_vectors_of_another_length_than_the_model_gives_are_reported(run, vectors):
    vectors.inspect.return_value = CollectionInfo(True, 1024, frozenset({"bge-multilingual-gemma2"}))

    _, result = run([], {"owner": _user("owner", "kc")})

    assert result["vector_problems"] == ["vectors of dimension 1024, while bge-multilingual-gemma2 gives 3"]


def test_the_length_of_a_model_is_learnt_once(run, backend):
    run([], {"owner": _user("owner", "kc")})
    run([], {"owner": _user("owner", "kc")})

    assert backend.embed.call_count == 1


def test_a_probe_that_fails_does_not_stop_the_copy_nor_report_anything(run, vectors, backend):
    vectors.inspect.return_value = CollectionInfo(True, 1024, frozenset({"bge-multilingual-gemma2"}))
    backend.embed.side_effect = RuntimeError("hub down")

    _, result = run([], {"owner": _user("owner", "kc")})

    assert result["vector_problems"] == []
    backend.sync_collection.assert_called_once()


def test_a_collection_missing_from_qdrant_is_a_problem_only_if_the_knowledge_base_has_files(run, vectors):
    vectors.inspect.return_value = CollectionInfo(False, None, frozenset())

    _, empty = run([], {"owner": _user("owner", "kc")})
    _, filled = run([], {"owner": _user("owner", "kc")}, files=[{"id": "f1"}])

    assert empty["vector_problems"] == []
    assert filled["vector_problems"] == ["its collection is not in Qdrant"]


def test_vectors_that_are_not_one_unnamed_vector_are_reported(run, vectors):
    vectors.inspect.return_value = CollectionInfo(True, None, frozenset({"bge-multilingual-gemma2"}))

    _, result = run([], {"owner": _user("owner", "kc")})

    assert result["vector_problems"] == [
        "its vectors are not one unnamed vector, which is not how Open WebUI writes them"
    ]


def test_what_is_wrong_with_the_vectors_goes_with_the_collection(run, vectors):
    vectors.inspect.return_value = CollectionInfo(True, 5, frozenset({"another-model"}))

    body, _ = run([], {"owner": _user("owner", "kc-owner")})

    assert body["vector_problems"] and any("another-model" in problem for problem in body["vector_problems"])
