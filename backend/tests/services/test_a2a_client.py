"""The A2A client (#a2a): fetching an agent's card as the one tool it is imported as, and a message sent to it."""

import pytest

from app.services.tools import a2a_client
from app.services.tools.mcp_client import ToolServerError


class FakeResponse:
    def __init__(self, status_code=200, json_body=None):
        self.status_code = status_code
        self._json = json_body or {}

    def json(self):
        return self._json


class FakeHttp:
    """What `httpx2.AsyncClient()` is replaced with: canned answers for `.get` (the card) and `.post` (the call),
    and what was asked of it."""

    def __init__(self, get_responses=None, post_response=None, raise_on_get=None):
        self.get_responses = list(get_responses or [])
        self.post_response = post_response
        self.raise_on_get = raise_on_get
        self.get_urls: list[str] = []
        self.posted: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.get_urls.append(url)
        if self.raise_on_get:
            raise self.raise_on_get
        return self.get_responses.pop(0)

    async def post(self, url, json):
        self.posted = json
        return self.post_response


@pytest.fixture(autouse=True)
def public(monkeypatch):
    async def ok(url):
        return url

    monkeypatch.setattr(a2a_client, "ensure_public", ok)


CARD = {
    "name": "RH Bot",
    "description": "Répond aux questions de ressources humaines.",
    "skills": [{"name": "Congés", "description": "Solde et demandes de congés"}],
}


def _http(monkeypatch, fake: FakeHttp) -> None:
    monkeypatch.setattr(a2a_client.httpx2, "AsyncClient", lambda **kwargs: fake)


async def test_the_agent_card_becomes_the_one_tool_with_its_skills_in_the_description(monkeypatch):
    fake = FakeHttp(get_responses=[FakeResponse(404), FakeResponse(200, CARD)])
    _http(monkeypatch, fake)

    tools = await a2a_client.list_tools("https://agent.example", None)

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == a2a_client.TOOL_NAME
    assert "RH Bot" in tool.description and "congés" in tool.description
    assert tool.input_schema["required"] == ["message"]
    # Handing the question to another agent is never run by itself (#a2a): it needs the person's agreement.
    assert tool.side_effect is True
    assert fake.get_urls == [
        "https://agent.example/.well-known/agent-card.json",
        "https://agent.example/.well-known/agent.json",
    ]


async def test_a_card_with_no_name_or_no_card_at_all_fails_cleanly(monkeypatch):
    _http(monkeypatch, FakeHttp(get_responses=[FakeResponse(404), FakeResponse(404)]))
    with pytest.raises(ToolServerError):
        await a2a_client.list_tools("https://agent.example", None)

    _http(monkeypatch, FakeHttp(get_responses=[FakeResponse(200, {"description": "sans nom"}), FakeResponse(404)]))
    with pytest.raises(ToolServerError):
        await a2a_client.list_tools("https://agent.example", None)


async def test_the_message_sent_is_the_tasks_own_argument_and_the_answer_is_read_from_a_message(monkeypatch):
    body = {"jsonrpc": "2.0", "id": "1", "result": {"parts": [{"kind": "text", "text": "12 jours"}]}}
    fake = FakeHttp(post_response=FakeResponse(200, body))
    _http(monkeypatch, fake)

    result = await a2a_client.call_tool("https://agent.example/rpc", "tok", "demander", {"message": "solde ?"})

    assert fake.posted["method"] == "message/send"
    assert fake.posted["params"]["message"]["parts"] == [{"kind": "text", "text": "solde ?"}]
    assert result.text == "12 jours" and result.is_error is False


async def test_the_answer_is_read_from_a_finished_tasks_status_message_or_its_artifacts(monkeypatch):
    via_status = {"result": {"status": {"message": {"parts": [{"kind": "text", "text": "via tâche"}]}}}}
    _http(monkeypatch, FakeHttp(post_response=FakeResponse(200, via_status)))
    assert (await a2a_client.call_tool("https://agent.example", None, "demander", {"message": "q"})).text == "via tâche"

    via_artifacts = {"result": {"artifacts": [{"parts": [{"kind": "text", "text": "via artefact"}]}]}}
    _http(monkeypatch, FakeHttp(post_response=FakeResponse(200, via_artifacts)))
    result = await a2a_client.call_tool("https://agent.example", None, "demander", {"message": "q"})
    assert result.text == "via artefact"


async def test_an_error_answer_is_reported_as_one_without_raising(monkeypatch):
    body = {"jsonrpc": "2.0", "id": "1", "error": {"message": "agent indisponible"}}
    _http(monkeypatch, FakeHttp(post_response=FakeResponse(200, body)))

    result = await a2a_client.call_tool("https://agent.example", None, "demander", {"message": "q"})

    assert result.is_error is True and result.text == "agent indisponible"


async def test_the_url_is_checked_before_a_card_is_fetched_or_a_message_sent(monkeypatch):
    async def refuse(url):
        from app.core.url_guard import UrlRefusedError

        raise UrlRefusedError("adresse refusée")

    monkeypatch.setattr(a2a_client, "ensure_public", refuse)

    with pytest.raises(ToolServerError) as list_error:
        await a2a_client.list_tools("http://10.0.0.1", None)
    with pytest.raises(ToolServerError) as call_error:
        await a2a_client.call_tool("http://10.0.0.1", None, "demander", {"message": "q"})

    assert list_error.value.code == "url_refusee" and call_error.value.code == "url_refusee"
