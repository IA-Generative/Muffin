import httpx
import pytest

from app.owui_client import OwuiClient, OwuiError


def _client(handler, **kwargs) -> OwuiClient:
    return OwuiClient("http://owui", "sk-test", transport=httpx.MockTransport(handler), sleep=lambda _: None, **kwargs)


def _user(n: int) -> dict:
    return {"id": f"u{n}", "email": f"u{n}@example.test", "name": f"User {n}", "role": "user", "extra": "ignored"}


def test_the_key_is_sent_as_a_bearer_token():
    seen = {}

    def handler(request):
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json=[])

    _client(handler).groups()
    assert seen["authorization"] == "Bearer sk-test"


def test_a_paginated_listing_is_read_until_an_empty_page():
    pages = {"1": [_user(1), _user(2)], "2": [_user(3)], "3": []}
    asked = []

    def handler(request):
        asked.append(request.url.params["page"])
        return httpx.Response(200, json={"users": pages[request.url.params["page"]], "total": 3})

    assert [user.id for user in _client(handler).users()] == ["u1", "u2", "u3"]
    assert asked == ["1", "2", "3"]


def test_a_transient_failure_is_tried_again_with_a_growing_pause():
    answers = iter([httpx.Response(503), httpx.ConnectError("down"), httpx.Response(200, json=[])])
    pauses = []

    def handler(request):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = OwuiClient(
        "http://owui", "k", transport=httpx.MockTransport(handler), sleep=pauses.append, backoff_seconds=1.0
    )
    assert client.groups() == []
    assert pauses == [1.0, 2.0]


def test_it_gives_up_after_the_attempts():
    client = _client(lambda request: httpx.Response(502), max_attempts=3)
    with pytest.raises(OwuiError, match="after 3 attempts"):
        client.groups()


def test_an_error_that_trying_again_would_not_change_fails_at_once():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"detail": "401 Unauthorized"})

    with pytest.raises(OwuiError, match="401"):
        _client(handler).groups()
    assert len(calls) == 1


def test_a_knowledge_base_carries_its_access_grants():
    body = {
        "items": [
            {
                "id": "kb1",
                "user_id": "u1",
                "name": "kb",
                "description": None,
                "access_grants": [
                    {"principal_type": "group", "principal_id": "g1", "permission": "read", "id": "x"},
                    {"principal_type": "user", "principal_id": "*", "permission": "write"},
                ],
            }
        ]
    }
    client = _client(
        lambda request: httpx.Response(200, json=body if request.url.params["page"] == "1" else {"items": []})
    )
    [knowledge] = list(client.knowledge_bases())
    assert [(g.principal_type, g.principal_id, g.permission) for g in knowledge.access_grants] == [
        ("group", "g1", "read"),
        ("user", "*", "write"),
    ]


def test_the_members_of_a_group_come_with_what_they_signed_in_with():
    asked = []

    def handler(request):
        asked.append(request.url.path)
        if request.url.path.endswith("/export"):
            return httpx.Response(200, json={"user_ids": ["u1"]})
        return httpx.Response(200, json={**_user(1), "oauth": {"oidc": {"sub": "kc-1"}}})

    [member] = list(_client(handler).group_members("g1"))
    assert member.keycloak_sub == "kc-1"
    assert asked == ["/api/v1/groups/id/g1/export", "/api/v1/users/u1"]


def test_a_knowledge_base_without_files_may_come_with_null_files():
    body = {"id": "kb1", "user_id": "u1", "name": "kb", "files": None}

    knowledge = _client(lambda request: httpx.Response(200, json=body)).knowledge("kb1")

    assert not knowledge.files
