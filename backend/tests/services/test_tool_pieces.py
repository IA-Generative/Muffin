"""The pieces under the tools of the chat (#343): exact calculation, dates, the guard on where a server may be, and the
client of an MCP server."""

import socket
from types import SimpleNamespace

import mcp_types as types
import pytest

from app.core import url_guard
from app.core.url_guard import UrlRefusedError, check_form, ensure_public
from app.services.tools import internal_catalog, mcp_client
from app.services.tools.internal_catalog import ToolArgumentError, evaluate
from app.services.tools.mcp_client import ToolServerError

# --- the calculation ---


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("1250 * 1.2 - 80", 1420.0),
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("2 ** 10", 1024),
        ("2 ^ 10", 1024),
        ("3,5 * 2", 7.0),
        ("10 / 4", 2.5),
        ("17 // 5 + 17 % 5", 5),
        ("sqrt(144) + abs(-3)", 15.0),
        ("max(3, 9, 4) - min(3, 9, 4)", 6),
        ("1200 × 12 ÷ 100", 144.0),
        ("-5 + +2", -3),
    ],
)
def test_an_expression_is_worked_out_exactly(expression, value):
    assert evaluate(expression) == pytest.approx(value)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "().__class__.__bases__",
        "open('/etc/passwd')",
        "x + 1",
        "'a' * 3",
        "[1, 2][0]",
        "lambda: 1",
        "2 ** 100000",
        "1 / 0",
        "1 +",
        "",
        "9" * 600,
        "+".join(["1"] * 300),
        "True + 1",
        "sqrt(-1)",
        "round(1, 2, 3, 4)",
        "abs(x=1)",
    ],
)
def test_nothing_but_arithmetic_is_accepted_and_nothing_is_run(expression):
    with pytest.raises(ToolArgumentError):
        evaluate(expression)


def test_the_calculator_tool_answers_with_the_expression_and_its_value():
    tool = internal_catalog.find("internal.calculatrice")

    assert tool.run({"expression": "1250 * 1.2 - 80"}) == "1250 * 1.2 - 80 = 1420"
    assert tool.run({"expression": "10 / 4"}) == "10 / 4 = 2.5"


# --- the dates ---


def run_dates(**arguments):
    return internal_catalog.find("internal.calcul_dates").run(arguments)


def test_dates_are_worked_out():
    assert run_dates(operation="jour_de_la_semaine", date="2024-02-29") == "2024-02-29 est un jeudi."
    assert "2024-03-30" in run_dates(operation="ajouter", date="2024-02-29", jours=30)
    assert "- 10 jours = 2024-02-19" in run_dates(operation="ajouter", date="2024-02-29", jours=-10)
    assert run_dates(operation="ecart", date="2024-01-01", autre_date="2024-12-31") == (
        "Entre 2024-01-01 et 2024-12-31 : 365 jours."
    )
    assert run_dates(operation="bornes_du_mois", date="2024-02-10") == "2024-02 : du 2024-02-01 au 2024-02-29."


def test_a_date_left_out_is_today():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.agent.graph.services.time_tool import DEFAULT_TIMEZONE

    # Today where the tool counts it: the machine's own day differs from it for an hour or two each night.
    today = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()

    assert today.isoformat() in run_dates(operation="jour_de_la_semaine")


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "supprimer"},
        {"operation": "ajouter", "date": "demain", "jours": 1},
        {"operation": "ajouter", "date": "2024-01-01", "jours": "beaucoup"},
        {"operation": "ajouter", "date": "2024-01-01", "jours": 10**9},
        {"operation": "ecart", "date": "2024-01-01", "autre_date": "n'importe quoi"},
    ],
)
def test_wrong_arguments_are_told_plainly(arguments):
    with pytest.raises(ToolArgumentError):
        run_dates(**arguments)


def test_no_tool_of_the_catalogue_changes_data():
    assert internal_catalog.INTERNAL_TOOLS and not any(tool.side_effect for tool in internal_catalog.INTERNAL_TOOLS)
    assert {tool.ref for tool in internal_catalog.INTERNAL_TOOLS} == {"internal.calculatrice", "internal.calcul_dates"}


# --- where a server may be ---


@pytest.fixture
def resolves(monkeypatch):
    """What the name of a server resolves to."""
    answer: dict[str, list[str]] = {}

    def fake(host, port):
        if host not in answer:
            raise socket.gaierror("unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in answer[host]]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake)
    return answer


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/mcp",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "//example.org/mcp",
        "https://user:secret@example.org/mcp",
        "https://:secret@example.org/mcp",
        "https:///mcp",
        "https://" + "a" * 3000 + ".org",
    ],
)
def test_an_address_of_the_wrong_form_is_refused(url):
    with pytest.raises(UrlRefusedError):
        check_form(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",  # the metadata service of the clouds
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
    ],
)
async def test_an_address_that_is_not_public_is_refused_whether_typed_or_resolved(address, resolves):
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(UrlRefusedError):
        await ensure_public(f"http://{host}/mcp")
    resolves["tools.example.org"] = [address]
    with pytest.raises(UrlRefusedError):
        await ensure_public("https://tools.example.org/mcp")


async def test_one_private_address_among_public_ones_is_enough_to_refuse(resolves):
    resolves["tools.example.org"] = ["93.184.216.34", "10.0.0.5"]

    with pytest.raises(UrlRefusedError):
        await ensure_public("https://tools.example.org/mcp")


async def test_a_name_that_resolves_to_a_public_address_is_accepted_and_one_that_does_not_resolve_is_not(resolves):
    resolves["tools.example.org"] = ["93.184.216.34"]

    assert await ensure_public("https://tools.example.org/mcp") == "https://tools.example.org/mcp"
    with pytest.raises(UrlRefusedError):
        await ensure_public("https://nowhere.example.org/mcp")


async def test_it_is_checked_at_each_call_so_a_name_that_changed_its_answer_is_caught(resolves):
    resolves["tools.example.org"] = ["93.184.216.34"]
    await ensure_public("https://tools.example.org/mcp")

    resolves["tools.example.org"] = ["127.0.0.1"]  # the rebinding

    with pytest.raises(UrlRefusedError):
        await ensure_public("https://tools.example.org/mcp")


async def test_only_the_allowed_domains_when_some_are_set(resolves, monkeypatch):
    monkeypatch.setattr(url_guard._settings, "TOOLS_ALLOWED_DOMAINS", "tools.gouv.fr, partner.org")
    resolves.update(
        {"api.tools.gouv.fr": ["93.184.216.34"], "evil.com": ["93.184.216.34"], "nottools.gouv.fr": ["93.184.216.34"]}
    )

    assert await ensure_public("https://api.tools.gouv.fr/mcp")
    for refused in ("https://evil.com/mcp", "https://nottools.gouv.fr/mcp", "https://tools.gouv.fr.evil.com/mcp"):
        with pytest.raises(UrlRefusedError):
            await ensure_public(refused)


async def test_a_developer_can_allow_private_addresses_and_nothing_else_changes(monkeypatch):
    monkeypatch.setattr(url_guard._settings, "TOOLS_ALLOW_PRIVATE_ADDRESSES", True)

    assert await ensure_public("http://127.0.0.1:9000/mcp")
    with pytest.raises(UrlRefusedError):
        await ensure_public("https://user:x@127.0.0.1/mcp")


# --- the client of an MCP server ---


class FakeClient:
    """The MCP client, answering what a test sets: `listed` for tools/list, `result` for a call, or raising `error`."""

    listed: list = []
    result = None
    error: Exception | None = None
    created: list = []

    def __init__(self, transport, **kwargs):
        FakeClient.created.append(transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_tools(self):
        if FakeClient.error:
            raise FakeClient.error
        return SimpleNamespace(tools=FakeClient.listed)

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        if FakeClient.error:
            raise FakeClient.error
        return FakeClient.result


@pytest.fixture
def remote(monkeypatch):
    FakeClient.listed, FakeClient.result, FakeClient.error, FakeClient.created = [], None, None, []
    monkeypatch.setattr(mcp_client, "Client", FakeClient)
    monkeypatch.setattr(mcp_client, "_transport", lambda url, token: ("transport", url, token))

    async def public(url):
        return url

    monkeypatch.setattr(mcp_client, "ensure_public", public)
    return FakeClient


def tool(name, description="d", schema=None, read_only=None):
    annotations = types.ToolAnnotations(read_only_hint=read_only) if read_only is not None else None
    return types.Tool(
        name=name, description=description, input_schema=schema or {"type": "object"}, annotations=annotations
    )


async def test_a_tool_is_only_safe_when_the_server_says_it_only_reads(remote):
    remote.listed = [tool("lire", read_only=True), tool("ecrire", read_only=False), tool("inconnu")]

    tools = await mcp_client.list_tools("https://x.example/mcp", "token")

    assert {t.name: t.side_effect for t in tools} == {"lire": False, "ecrire": True, "inconnu": True}
    assert remote.created == [("transport", "https://x.example/mcp", "token")]


async def test_what_a_server_describes_is_bounded(remote, monkeypatch):
    monkeypatch.setattr(mcp_client._settings, "TOOLS_PER_SERVER_MAX", 2)
    huge = {"type": "object", "properties": {"x": {"description": "y" * 20000}}}
    remote.listed = [tool("a", description="z" * 5000, schema=huge), tool("b" * 200), tool("c"), tool("d")]

    tools = await mcp_client.list_tools("https://x.example/mcp", None)

    # Two taken at most, the one named too long dropped; the description cut; the oversized schema replaced.
    assert [t.name for t in tools] == ["a"]
    assert len(tools[0].description) == 2000 and tools[0].input_schema == {"type": "object"}


async def test_an_answer_is_cut_and_what_is_not_text_is_said_to_be_left_out(remote, monkeypatch):
    monkeypatch.setattr(mcp_client._settings, "TOOLS_OUTPUT_MAX_CHARS", 20)
    remote.result = types.CallToolResult(
        content=[
            types.TextContent(type="text", text="x" * 50),
            types.ImageContent(type="image", data="aGk=", mime_type="image/png"),
        ],
        is_error=False,
    )

    result = await mcp_client.call_tool("https://x.example/mcp", None, "t", {})

    assert len(result.text) == 20 and result.truncated is True and result.is_error is False


async def test_the_error_a_tool_reports_is_kept_as_an_error(remote):
    remote.result = types.CallToolResult(
        content=[types.TextContent(type="text", text="dossier introuvable")], is_error=True
    )

    result = await mcp_client.call_tool("https://x.example/mcp", None, "t", {})

    assert result.is_error and result.text == "dossier introuvable"


async def test_a_server_that_does_not_answer_gives_a_stable_code_and_a_slow_one_another(remote):
    remote.error = ConnectionError("boom")
    with pytest.raises(ToolServerError) as down:
        await mcp_client.call_tool("https://x.example/mcp", None, "t", {})
    remote.error = TimeoutError()
    with pytest.raises(ToolServerError) as slow:
        await mcp_client.call_tool("https://x.example/mcp", None, "t", {})

    assert (down.value.code, slow.value.code) == ("serveur_injoignable", "delai_depasse")
    assert "boom" not in down.value.message  # what the network said is not for the person


async def test_an_address_that_is_refused_is_never_connected_to(monkeypatch):
    FakeClient.created = []
    monkeypatch.setattr(mcp_client, "Client", FakeClient)

    async def refuse(url):
        raise UrlRefusedError("privée")

    monkeypatch.setattr(mcp_client, "ensure_public", refuse)

    with pytest.raises(ToolServerError) as error:
        await mcp_client.call_tool("http://10.0.0.1/mcp", None, "t", {})

    assert error.value.code == "url_refusee" and FakeClient.created == []
