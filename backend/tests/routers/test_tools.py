"""The tools the chat may call (#343): who sees which server and tool, what a call may do, and what is kept of it."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import secret_store
from app.core.secret_store import LocalProvider
from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.stored_secret import StoredSecret
from app.models.tool import Tool, ToolCallLog, ToolServer
from app.services import tool_service
from app.services.tools import mcp_client
from app.services.tools.mcp_client import RemoteResult, RemoteTool, ToolServerError

ALICE, BOB, CARL = "alice", "bob", "carl"
PUBLIC = "http://93.184.216.34/mcp?key=SECRET-IN-URL"  # a public address typed as it is: no name to resolve
WORKER_KEY = "test-worker-key"
SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"], "additionalProperties": False}


def _as(user_id: str, groups: list[str] | None = None):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False, groups=groups or []
        )

    return override


class Remote:
    """The MCP server out there: what it lists, what it answers, and what it was asked."""

    def __init__(self) -> None:
        self.listed = [
            RemoteTool("chercher", "Cherche un dossier", SCHEMA, side_effect=False),
            RemoteTool("supprimer", "Supprime un dossier", SCHEMA, side_effect=True),
        ]
        self.result = RemoteResult(text="dossier 12 : en cours", is_error=False, truncated=False)
        self.error: ToolServerError | None = None
        self.calls: list[tuple[str, str | None, str, dict]] = []

    async def list_tools(self, url, token):
        if self.error:
            raise self.error
        return self.listed

    async def call_tool(self, url, token, name, arguments):
        self.calls.append((url, token, name, arguments))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def remote(monkeypatch):
    fake = Remote()
    monkeypatch.setattr(mcp_client, "list_tools", fake.list_tools)
    monkeypatch.setattr(mcp_client, "call_tool", fake.call_tool)
    return fake


@pytest.fixture
async def client(monkeypatch, remote):
    monkeypatch.setattr(secret_store, "_provider", LocalProvider([("k1", bytes([1]) * 32)]))
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    app.dependency_overrides[get_current_user] = _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(ToolCallLog))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(ToolServer))
        await session.execute(delete(StoredSecret))
        await session.commit()


def become(user_id: str, groups: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = _as(user_id, groups)


async def add_server(client, name="Dossiers", **fields) -> dict:
    response = await client.post("/api/tool-servers", json={"name": name, "url": PUBLIC, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def ref_of(server: dict, name: str) -> str:
    return next(tool["ref"] for tool in server["tools"] if tool["name"] == name)


async def make_run(user_id: str = ALICE, groups: list[str] | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="t")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="q")
        session.add(message)
        await session.flush()
        run = Run(
            user_id=user_id, message_id=message.id, conversation_id=conversation.id, query="q", user_groups=groups or []
        )
        session.add(run)
        await session.commit()
        return run.id, conversation.id


async def call(client, run_id, ref, arguments=None):
    response = await client.post(
        "/api/internal/tools/call",
        headers={"X-API-Key": WORKER_KEY},
        json={"run_id": str(run_id), "ref": ref, "arguments": arguments or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- adding a server ---


async def test_a_server_is_added_with_its_tools_imported_and_marked_when_they_may_change_data(client):
    server = await add_server(client)

    assert server["is_owner"] and server["visibility"] == "private" and server["last_error"] is None
    assert {t["name"]: t["side_effect"] for t in server["tools"]} == {"chercher": False, "supprimer": True}


async def test_an_address_that_is_not_public_or_not_well_formed_is_refused_with_the_reason(client):
    for url in (
        "http://127.0.0.1:9000/mcp",
        "http://169.254.169.254/latest",
        "https://user:pw@93.184.216.34/mcp",
        "ftp://93.184.216.34/x",
    ):
        response = await client.post("/api/tool-servers", json={"name": "x", "url": url})
        assert response.status_code == 422, url
        assert response.json()["detail"]
    assert (await client.get("/api/tool-servers")).json() == []


async def test_a_server_that_does_not_answer_is_added_with_the_reason_and_keeps_its_tools_when_it_goes_down(
    client, remote
):
    remote.error = ToolServerError("serveur_injoignable", "Le serveur n'a pas répondu (ConnectionError).")
    down = await add_server(client, name="Éteint")
    remote.error = None
    up = await add_server(client, name="Allumé")
    remote.error = ToolServerError("serveur_injoignable", "Le serveur n'a pas répondu (ConnectionError).")

    resynced = (await client.post(f"/api/tool-servers/{up['id']}/sync")).json()

    assert down["tools"] == [] and "n'a pas répondu" in down["last_error"]
    assert len(resynced["tools"]) == 2 and resynced["last_error"]


async def test_synchronising_takes_the_tools_again_and_drops_those_that_are_gone(client, remote):
    server = await add_server(client)
    remote.listed = [
        RemoteTool("chercher", "Nouvelle description", SCHEMA, side_effect=False),
        RemoteTool("nouveau", "n", SCHEMA, False),
    ]

    synced = (await client.post(f"/api/tool-servers/{server['id']}/sync")).json()

    assert {t["name"] for t in synced["tools"]} == {"chercher", "nouveau"}
    assert next(t for t in synced["tools"] if t["name"] == "chercher")["description"] == "Nouvelle description"
    assert synced["last_synced_at"] and synced["last_error"] is None


async def test_the_number_of_servers_a_person_may_add_is_limited(client, monkeypatch):
    monkeypatch.setattr(tool_service._settings, "TOOL_SERVERS_PER_USER", 1)
    await add_server(client)

    assert (await client.post("/api/tool-servers", json={"name": "Deux", "url": PUBLIC})).status_code == 409


# --- the token ---


async def test_a_token_is_kept_encrypted_used_to_call_and_never_given_back(client, remote):
    server = await add_server(client, auth_mode="bearer", token="jeton-de-test")
    run_id, _ = await make_run()

    await call(client, run_id, ref_of(server, "chercher"), {"q": "x"})

    assert server["has_token"] is True and "jeton-de-test" not in str(server)
    assert remote.calls[-1][1] == "jeton-de-test"
    async with async_session_factory() as session:
        stored = (await session.execute(select(StoredSecret))).scalar_one()
    assert "jeton-de-test" not in stored.ciphertext and stored.owner_id == ALICE
    assert "jeton-de-test" not in (await client.get("/api/tool-servers")).text
    assert "jeton-de-test" not in (await client.get(f"/api/tool-servers/{server['id']}")).text


async def test_a_server_that_wants_a_token_needs_one_and_dropping_the_auth_deletes_the_token(client):
    assert (
        await client.post("/api/tool-servers", json={"name": "x", "url": PUBLIC, "auth_mode": "bearer"})
    ).status_code == 422
    server = await add_server(client, auth_mode="bearer", token="jeton-de-test")

    updated = await client.patch(f"/api/tool-servers/{server['id']}", json={"auth_mode": "none"})

    assert updated.json()["has_token"] is False
    async with async_session_factory() as session:
        assert (await session.execute(select(StoredSecret))).first() is None


async def test_deleting_a_server_deletes_its_tools_and_its_token(client):
    server = await add_server(client, auth_mode="bearer", token="jeton-de-test")

    assert (await client.delete(f"/api/tool-servers/{server['id']}")).status_code == 204

    async with async_session_factory() as session:
        assert (await session.execute(select(Tool))).first() is None
        assert (await session.execute(select(StoredSecret))).first() is None


# --- who sees which server ---


async def test_a_private_server_is_seen_and_used_by_nobody_else_even_by_naming_it(client, remote):
    server = await add_server(client)
    become(BOB)
    url = f"/api/tool-servers/{server['id']}"

    assert (await client.get("/api/tool-servers")).json() == []
    assert (await client.get(url)).status_code == 404
    assert (await client.patch(url, json={"name": "à moi"})).status_code == 404
    assert (await client.delete(url)).status_code == 404
    assert (await client.post(f"{url}/sync")).status_code == 404
    run_id, _ = await make_run(BOB)
    result = await call(client, run_id, ref_of(server, "chercher"), {"q": "x"})
    assert (result["ok"], result["code"]) == (False, "outil_indisponible") and remote.calls == []
    assert server["name"] not in str((await client.get("/api/tools")).json())


async def test_a_server_shared_with_a_group_reaches_its_members_who_see_where_it_is_and_not_how_to_reach_it(
    client, remote
):
    become(ALICE, ["/rh"])
    server = await add_server(client, visibility="groups", group_ids=["/rh"])
    become(BOB, ["/rh"])
    listed = (await client.get("/api/tool-servers")).json()
    run_id, _ = await make_run(BOB, ["/rh"])

    result = await call(client, run_id, ref_of(server, "chercher"), {"q": "x"})

    assert [s["id"] for s in listed] == [server["id"]]
    assert listed[0]["is_owner"] is False and listed[0]["url"] == "http://93.184.216.34"  # no path, no key
    assert "SECRET-IN-URL" not in str(listed) and listed[0]["group_ids"] == [] and listed[0]["last_error"] is None
    assert result["ok"] is True
    become(CARL, ["/finance"])
    assert (await client.get("/api/tool-servers")).json() == []


async def test_a_server_shared_with_everyone_is_seen_by_everyone_and_changed_by_nobody_else(client):
    server = await add_server(client, visibility="all")
    become(BOB)

    assert [s["id"] for s in (await client.get("/api/tool-servers")).json()] == [server["id"]]
    assert (await client.patch(f"/api/tool-servers/{server['id']}", json={"name": "à moi"})).status_code == 403
    assert (await client.delete(f"/api/tool-servers/{server['id']}")).status_code == 403
    assert (await client.post(f"/api/tool-servers/{server['id']}/sync")).status_code == 403


async def test_one_only_shares_with_a_group_one_is_in(client):
    refused = await client.post(
        "/api/tool-servers", json={"name": "x", "url": PUBLIC, "visibility": "groups", "group_ids": ["/direction"]}
    )
    none = await client.post(
        "/api/tool-servers", json={"name": "x", "url": PUBLIC, "visibility": "groups", "group_ids": []}
    )

    assert refused.status_code == 422 and none.status_code == 422


async def test_a_server_switched_off_offers_nothing_but_stays_with_its_owner(client):
    server = await add_server(client, visibility="all")
    await client.patch(f"/api/tool-servers/{server['id']}", json={"enabled": False})

    assert [s["id"] for s in (await client.get("/api/tool-servers")).json()] == [server["id"]]
    assert all(t["server_id"] is None for t in (await client.get("/api/tools")).json())
    become(BOB)
    assert (await client.get("/api/tool-servers")).json() == []


# --- what the chat is offered ---


async def test_the_catalogue_of_muffin_and_the_servers_tools_are_listed_with_why_one_is_not_available(client):
    server = await add_server(client)

    tools = {t["name"]: t for t in (await client.get("/api/tools")).json()}

    assert tools["calculatrice"]["available"] and tools["calcul_dates"]["available"]
    assert tools["chercher"]["available"] and tools["chercher"]["server_name"] == "Dossiers"
    assert tools["supprimer"]["available"] is False and "modifie des données" in tools["supprimer"]["reason"]
    assert tools["supprimer"]["ref"] == ref_of(server, "supprimer")


async def test_what_the_model_is_given_leaves_out_what_changes_data_and_is_bounded(client, monkeypatch):
    await add_server(client)
    run_id, _ = await make_run()

    names = [t["name"] for t in (await _definitions(client, run_id))]
    monkeypatch.setattr(tool_service._settings, "TOOLS_OFFERED_MAX", 2)

    assert names == ["calculatrice", "calcul_dates", "chercher"]
    assert len(await _definitions(client, run_id)) == 2


async def _definitions(client, run_id):
    response = await client.post(
        "/api/internal/tools/definitions", headers={"X-API-Key": WORKER_KEY}, json={"run_id": str(run_id)}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_person_removes_tools_for_a_conversation_and_the_model_no_longer_gets_them(client, remote):
    server = await add_server(client)
    run_id, conversation_id = await make_run()
    chercher = ref_of(server, "chercher")

    removed = await client.put(
        f"/api/conversations/{conversation_id}/tools", json={"disabled_refs": [chercher, "internal.calculatrice"]}
    )
    listed = {
        t["name"]: t for t in (await client.get("/api/tools", params={"conversation_id": str(conversation_id)})).json()
    }
    result = await call(client, run_id, chercher, {"q": "x"})

    assert removed.status_code == 200
    assert listed["chercher"]["available"] is False and listed["chercher"]["reason"] == "retiré pour cette conversation"
    assert "chercher" not in [t["name"] for t in await _definitions(client, run_id)]
    assert (result["ok"], result["code"]) == (False, "outil_indisponible") and remote.calls == []
    # Without the conversation they are all there: it only ever removes.
    assert next(t for t in (await client.get("/api/tools")).json() if t["name"] == "chercher")["available"]


async def test_nobody_removes_tools_in_the_conversation_of_someone_else(client):
    _, conversation_id = await make_run(ALICE)
    become(BOB)

    assert (
        await client.put(
            f"/api/conversations/{conversation_id}/tools", json={"disabled_refs": ["internal.calculatrice"]}
        )
    ).status_code == 404


# --- a call ---


async def test_a_tool_of_muffin_is_called_and_a_tool_of_a_server_too_with_the_arguments_given(client, remote):
    server = await add_server(client)
    run_id, _ = await make_run()

    maths = await call(client, run_id, "internal.calculatrice", {"expression": "2 + 2"})
    found = await call(client, run_id, ref_of(server, "chercher"), {"q": "dossier 12"})

    assert (maths["ok"], maths["text"]) == (True, "2 + 2 = 4")
    assert (found["ok"], found["text"], found["server_name"]) == (True, "dossier 12 : en cours", "Dossiers")
    assert remote.calls == [(PUBLIC, None, "chercher", {"q": "dossier 12"})]


async def test_arguments_that_do_not_fit_the_schema_are_refused_before_the_server_is_asked(client, remote):
    server = await add_server(client)
    run_id, _ = await make_run()

    for arguments in ({}, {"q": 12}, {"q": "x", "extra": 1}, {"q": "x" * 9000}):
        result = await call(client, run_id, ref_of(server, "chercher"), arguments)
        assert (result["ok"], result["code"]) == (False, "arguments_invalides")
    wrong_calculation = await call(client, run_id, "internal.calculatrice", {"expression": "__import__('os')"})

    assert remote.calls == [] and wrong_calculation["code"] == "arguments_invalides"


async def test_a_tool_that_changes_data_is_never_called_without_approval(client, remote):
    server = await add_server(client)
    run_id, _ = await make_run()

    result = await call(client, run_id, ref_of(server, "supprimer"), {"q": "dossier 12"})

    assert (result["ok"], result["code"]) == (False, "confirmation_requise") and remote.calls == []


async def test_a_name_that_is_not_a_tool_is_not_one(client):
    run_id, _ = await make_run()

    for ref in ("internal.inexistant", str(uuid.uuid4()), "n'importe quoi", "internal."):
        assert (await call(client, run_id, ref))["code"] == "outil_indisponible"


async def test_what_goes_wrong_out_there_is_a_stable_code_never_an_error_and_never_what_the_network_said(
    client, remote
):
    server = await add_server(client)
    run_id, _ = await make_run()
    chercher = ref_of(server, "chercher")

    remote.error = ToolServerError("delai_depasse", "Le serveur a mis trop de temps à répondre.")
    slow = await call(client, run_id, chercher, {"q": "x"})
    remote.error = ToolServerError("url_refusee", "Cette adresse n'est pas publique.")
    refused = await call(client, run_id, chercher, {"q": "x"})
    remote.error = None
    remote.result = RemoteResult(text="dossier introuvable", is_error=True, truncated=False)
    failed = await call(client, run_id, chercher, {"q": "x"})
    remote.result = RemoteResult(text="x" * 10, is_error=False, truncated=True)
    cut = await call(client, run_id, chercher, {"q": "x"})

    assert [r["code"] for r in (slow, refused, failed)] == ["delai_depasse", "url_refusee", "erreur_outil"]
    assert not any(r["ok"] for r in (slow, refused, failed)) and (cut["ok"], cut["truncated"]) == (True, True)


async def test_a_call_is_made_for_the_person_of_the_run_whatever_else_is_sent(client, remote):
    server = await add_server(client)  # Alice's, private
    run_id, _ = await make_run(BOB)  # a run of Bob

    result = await call(client, run_id, ref_of(server, "chercher"), {"q": "x"})

    assert result["code"] == "outil_indisponible" and remote.calls == []
    assert (
        await client.post("/api/internal/tools/call", json={"run_id": str(run_id), "ref": "internal.calculatrice"})
    ).status_code == 401
    unknown = await client.post(
        "/api/internal/tools/call",
        headers={"X-API-Key": WORKER_KEY},
        json={"run_id": str(uuid.uuid4()), "ref": "internal.calculatrice"},
    )
    assert unknown.status_code == 404


# --- quotas ---


async def test_a_run_may_call_a_few_tools_and_past_that_the_answer_is_a_code_not_a_failure(client, monkeypatch):
    monkeypatch.setattr(tool_service._settings, "TOOLS_CALLS_PER_RUN", 2)
    run_id, _ = await make_run()
    other_run, _ = await make_run()

    codes = [(await call(client, run_id, "internal.calculatrice", {"expression": "1+1"}))["code"] for _ in range(4)]
    fresh = await call(client, other_run, "internal.calculatrice", {"expression": "1+1"})

    assert codes == ["ok", "ok", "quota_depasse", "quota_depasse"] and fresh["ok"] is True


async def test_a_person_has_a_quota_per_minute_across_their_runs(client, monkeypatch):
    monkeypatch.setattr(tool_service._settings, "TOOLS_CALLS_PER_USER_PER_MINUTE", 3)
    codes = []
    for _ in range(5):
        run_id, _ = await make_run("quota-person")
        codes.append((await call(client, run_id, "internal.calculatrice", {"expression": "1+1"}))["code"])

    assert codes == ["ok", "ok", "ok", "quota_depasse", "quota_depasse"]


# --- the journal ---


async def test_the_journal_keeps_who_what_how_long_and_how_it_ended_and_never_the_arguments_nor_the_answer(
    client, remote
):
    server = await add_server(client)
    run_id, _ = await make_run()
    await call(client, run_id, "internal.calculatrice", {"expression": "1234 * 5678 + 99"})
    await call(client, run_id, ref_of(server, "chercher"), {"q": "DONNEE-PERSONNELLE-DUPONT"})
    await call(client, run_id, ref_of(server, "chercher"), {"q": 12})

    async with async_session_factory() as session:
        rows = (await session.execute(select(ToolCallLog).order_by(ToolCallLog.created_at))).scalars().all()
    assert [(row.user_id, row.outcome) for row in rows] == [
        (ALICE, "ok"),
        (ALICE, "ok"),
        (ALICE, "arguments_invalides"),
    ]
    assert rows[0].tool_ref == "internal.calculatrice" and rows[1].server_id == uuid.UUID(server["id"])
    assert all(row.run_id == run_id and row.duration_ms >= 0 for row in rows)
    everything = " ".join(str(value) for row in rows for value in vars(row).values())
    assert "DONNEE-PERSONNELLE" not in everything and "7006" not in everything and "dossier 12" not in everything
