"""The Muffin tool of Open WebUI (#476), file `docker/owui/muffin_search_tool.py`: how it turns the answer of Muffin's
MCP server into the citations Open WebUI shows, what it tells the model, and what it does when Muffin does not
answer."""

import asyncio
import importlib.util
import pathlib

import httpx
import pytest

PATH = pathlib.Path(__file__).resolve().parents[3] / "docker" / "owui" / "muffin_search_tool.py"
spec = importlib.util.spec_from_file_location("muffin_search_tool", PATH)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def _source(name="conges.pdf", document_id="d1", text="Dix jours par an", page=3, kind="chunk", score=0.7):
    return {
        "kind": kind,
        "text": text,
        "score": score,
        "document_id": document_id,
        "document_name": name,
        "page": page,
        "collection_id": "c1",
        "collection_name": "Congés",
        "url": f"http://muffin/collections/c1/documents/{document_id}",
    }


def _sub_query(text, sources, collections=("Congés",)):
    return {"text": text, "collections": [{"id": "c1", "name": name} for name in collections], "sources": sources}


@pytest.fixture(autouse=True)
def _numbers():
    tool._SOURCE_COUNT.clear()


# -- who is asking -------------------------------------------------------------------------------------------


def test_the_user_s_own_keycloak_token_is_used_before_the_valve():
    assert tool.access_token({"access_token": "mine", "id_token": "x"}, "valve") == "mine"


def test_the_valve_is_the_token_of_a_user_without_a_keycloak_session():
    assert tool.access_token(None, "valve") == "valve"
    assert tool.access_token({}, "valve") == "valve"


def test_no_token_at_all_is_none():
    assert tool.access_token(None, "") is None


# -- the sources of a search ---------------------------------------------------------------------------------


def test_the_passages_of_a_document_are_one_source_and_one_found_twice_is_kept_once():
    sub_queries = [
        _sub_query(
            "a", [_source(text="un"), _source(text="deux"), _source(name="b.pdf", document_id="d2", text="trois")]
        ),
        _sub_query("b", [_source(text="un"), _source(text="quatre")]),
    ]

    entries = tool.group_by_document(sub_queries)

    assert [(entry["name"], [p["text"] for p in entry["passages"]]) for entry in entries] == [
        ("conges.pdf", ["un", "deux", "quatre"]),
        ("b.pdf", ["trois"]),
    ]


def test_a_question_about_no_document_is_a_source_of_its_collection():
    entries = tool.group_by_document([_sub_query("a", [{**_source(), "document_id": None, "document_name": None}])])

    assert [(entry["name"], entry["url"]) for entry in entries] == [
        ("Congés", "http://muffin/collections/c1/documents/d1")
    ]


def test_a_citation_carries_what_open_webui_shows_of_a_source():
    entries = tool.group_by_document(
        [_sub_query("a", [_source(text="x" * 50), _source(text="court", page=None, kind="summary")])]
    )

    [event] = tool.citation_events(entries, limit=10)

    assert event["type"] == "citation"
    data = event["data"]
    assert data["source"] == {"name": "conges.pdf", "url": "http://muffin/collections/c1/documents/d1"}
    assert data["document"] == ["x" * 10, "court"]
    assert [(m["page"], m["kind"], m["name"], m["collection"]) for m in data["metadata"]] == [
        (3, "chunk", "conges.pdf", "Congés"),
        (None, "summary", "conges.pdf", "Congés"),
    ]
    assert all(m["source"] == data["source"]["url"] for m in data["metadata"])
    # Open WebUI labels a source with its link, unless it is told the source is external: the name is what is shown.
    assert all(m["external"] is True for m in data["metadata"])
    assert data["distances"] == [0.7, 0.7]


def test_the_model_reads_the_sources_under_the_numbers_open_webui_gives_them():
    sub_queries = [
        _sub_query("congés ?", [_source()]),
        _sub_query("télétravail ?", [_source(name="b.pdf", document_id="d2")]),
    ]
    entries = tool.group_by_document(sub_queries)

    text = tool.render_search(sub_queries, entries, first_number=3, limit=100)

    assert "[3] conges.pdf, page 3 (chunk) : Dix jours par an" in text
    assert "[4] b.pdf, page 3 (chunk)" in text
    assert "## congés ?" in text and "Collections cherchées : Congés" in text
    assert "n'ouvre aucun fichier" in text


def test_a_sub_question_with_no_source_says_so():
    text = tool.render_search([_sub_query("rien", [])], [], first_number=1, limit=100)

    assert "Aucune source trouvée." in text


def test_the_collections_are_listed_with_their_path_and_the_way_to_search_them():
    text = tool.render_collections(
        [
            {
                "id": "c1",
                "name": "Congés",
                "path": ["RH", "Congés"],
                "description": "Poser des congés",
                "url": "http://m/c1",
            }
        ]
    )

    assert "- RH › Congés (id c1, http://m/c1) : Poser des congés" in text
    assert "`search`" in text and "collection_ids" in text


def test_no_collection_says_so():
    assert "Aucune collection" in tool.render_collections([])


def test_the_sources_of_a_message_are_numbered_across_its_calls_and_not_across_messages():
    assert tool.next_number("m1") == 1
    tool.used_numbers("m1", 2)
    assert tool.next_number("m1") == 3
    assert tool.next_number("m2") == 1
    assert tool.next_number(None) == 1


def test_only_the_latest_messages_are_remembered(monkeypatch):
    monkeypatch.setattr(tool, "_KEPT_MESSAGES", 2)
    for message in ("a", "b", "c"):
        tool.next_number(message)
        tool.used_numbers(message, 1)

    assert set(tool._SOURCE_COUNT) == {"b", "c"}


# -- Muffin's answer -----------------------------------------------------------------------------------------


def _muffin(monkeypatch, handler):
    """Muffin's MCP server replaced by `handler(request) -> httpx.Response`."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(tool.httpx, "AsyncClient", lambda **kwargs: real(transport=transport, **kwargs))


def _ok(structured):
    return httpx.Response(
        200, json={"jsonrpc": "2.0", "id": 1, "result": {"isError": False, "structuredContent": structured}}
    )


def test_a_call_to_muffin_is_one_json_rpc_request_with_the_users_token(monkeypatch):
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return _ok({"collections": []})

    _muffin(monkeypatch, handler)

    result = asyncio.run(tool.call_muffin("http://muffin/api/mcp/", "tok", "suggest_collections", {"query": "q"}, 5))

    assert result == {"collections": []} and seen["auth"] == "Bearer tok"
    assert b'"method":"tools/call"' in seen["body"].replace(b" ", b"") and b"suggest_collections" in seen["body"]


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(401), "se reconnecter"),
        (httpx.Response(500), "a répondu 500"),
        (httpx.Response(200, text="not json"), "inattendu"),
        (
            httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"text": "pas lisible"}]}}
            ),
            "pas lisible",
        ),
        (httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"isError": False}}), "résultat structuré"),
    ],
)
def test_what_muffin_gets_wrong_is_worded_for_the_model(monkeypatch, response, message):
    _muffin(monkeypatch, lambda request: response)

    with pytest.raises(tool.MuffinError, match=message):
        asyncio.run(tool.call_muffin("http://muffin/api/mcp/", "tok", "search", {}, 5))


def test_a_muffin_that_does_not_answer_is_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    _muffin(monkeypatch, handler)

    with pytest.raises(tool.MuffinError, match="injoignable"):
        asyncio.run(tool.call_muffin("http://muffin/api/mcp/", "tok", "search", {}, 5))


# -- the tool ------------------------------------------------------------------------------------------------


def _tools(monkeypatch, result=None, error=None):
    calls = []

    async def call_muffin(url, token, name, arguments, timeout):
        calls.append((url, token, name, arguments))
        if error:
            raise error
        return result

    monkeypatch.setattr(tool, "call_muffin", call_muffin)
    return tool.Tools(), calls


def test_a_search_sends_the_citations_and_gives_the_model_the_sources(monkeypatch):
    result = {"sub_queries": [_sub_query("congés", [_source(), _source(name="b.pdf", document_id="d2")])]}
    tools, calls = _tools(monkeypatch, result)
    events = []

    async def emitter(event):
        events.append(event)

    text = asyncio.run(
        tools.search(
            "congés ?",
            ["c1"],
            __event_emitter__=emitter,
            __oauth_token__={"access_token": "tok"},
            __metadata__={"message_id": "m1"},
        )
    )

    assert [(event["type"], event["data"]["source"]["name"]) for event in events] == [
        ("citation", "conges.pdf"),
        ("citation", "b.pdf"),
    ]
    assert "[1] conges.pdf" in text and "[2] b.pdf" in text
    assert calls == [("http://backend:8000/api/mcp/", "tok", "search", {"query": "congés ?", "collection_ids": ["c1"]})]


def test_a_second_search_in_a_message_goes_on_numbering(monkeypatch):
    result = {"sub_queries": [_sub_query("q", [_source()])]}
    tools, _ = _tools(monkeypatch, result)
    kwargs = {"__oauth_token__": {"access_token": "tok"}, "__metadata__": {"message_id": "m1"}}

    first = asyncio.run(tools.search("q", **kwargs))
    second = asyncio.run(tools.search("q", **kwargs))

    assert "[1] conges.pdf" in first and "[2] conges.pdf" in second


def test_without_an_event_emitter_the_search_still_answers(monkeypatch):
    tools, _ = _tools(monkeypatch, {"sub_queries": [_sub_query("q", [_source()])]})

    assert "[1] conges.pdf" in asyncio.run(tools.search("q", __oauth_token__={"access_token": "tok"}))


def test_a_user_who_did_not_sign_in_through_keycloak_is_told_so_not_failed(monkeypatch):
    tools, calls = _tools(monkeypatch, {})

    for text in (asyncio.run(tools.search("q")), asyncio.run(tools.suggest_collections("q"))):
        assert "pas connecté par Keycloak" in text
    assert calls == []


def test_an_error_of_muffin_reaches_the_model_as_text(monkeypatch):
    tools, _ = _tools(monkeypatch, error=tool.MuffinError("Muffin est injoignable (ConnectError)."))
    events = []

    async def emitter(event):
        events.append(event)

    text = asyncio.run(tools.search("q", __event_emitter__=emitter, __oauth_token__={"access_token": "tok"}))

    assert text == "Muffin est injoignable (ConnectError)." and events == []


def test_the_tool_does_not_ask_open_webui_to_cite_its_whole_result(monkeypatch):
    assert tool.Tools().citation is False


def test_suggested_collections_are_listed_for_the_model(monkeypatch):
    tools, calls = _tools(
        monkeypatch,
        {"collections": [{"id": "c1", "name": "Congés", "path": ["Congés"], "description": "d", "url": "http://m/c1"}]},
    )

    text = asyncio.run(tools.suggest_collections("congés", 3, __oauth_token__={"access_token": "tok"}))

    assert "- Congés (id c1" in text and calls[0][3] == {"query": "congés", "limit": 3}
