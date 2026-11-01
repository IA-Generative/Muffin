"""Finding the tools of the chat by what they do (#530): the rights come first and the search only ranks inside
them, the model is given few tools when there are many, and nothing fails when the embedding model or the index is
down."""
# ruff: noqa: F811 - the fixtures of the tool tests are imported, and used by name

import json

from sqlalchemy import update

from app.db import async_session_factory
from app.models.run import Run
from app.services import tool_search_service, vector_store
from app.services.tool_search_service import point_id
from app.services.tools.mcp_client import RemoteTool
from tests.routers.test_tools import (  # noqa: F401 - the fixtures of the tool tests
    ALICE,
    BOB,
    CARL,
    SCHEMA,
    _definitions,
    add_server,
    become,
    client,
    make_run,
    ref_of,
    remote,
)
from tests.services.test_tool_search import embeddings  # noqa: F401

CURRENCY = RemoteTool("convertir", "Convertit un montant d'une devise dans une autre (taux de change)", SCHEMA, False)
PERSONNEL = RemoteTool("fiche_agent", "Retrouve le dossier personnel d'un agent", SCHEMA, False)
WEATHER = RemoteTool("previsions", "Donne la météo et la température du jour", SCHEMA, False)


def catalogue(extra: int = 27) -> list[RemoteTool]:
    """A long list of tools of one server: three that do something, the others nothing the questions are about."""
    return [CURRENCY, PERSONNEL, WEATHER] + [
        RemoteTool(f"outil_{i}", "Sans rapport avec les sujets", SCHEMA, False) for i in range(extra)
    ]


async def ask(run_id, query: str) -> None:
    async with async_session_factory() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(query=query))
        await session.commit()


async def search(client, q: str, **params) -> list[dict]:
    response = await client.get("/api/tools/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def names(tools: list[dict]) -> list[str]:
    return [tool["name"] for tool in tools]


# --- the interface: a search among the tools the person may use ---


async def test_a_need_described_in_a_sentence_finds_the_tool_that_covers_it_and_says_how_it_was_matched(
    client, remote, embeddings
):
    remote.listed = catalogue()
    await add_server(client)

    hits = await search(client, "quelle monnaie pour ce change ?")

    assert hits[0]["name"] == "convertir" and hits[0]["match"] == "hybrid" and hits[0]["server_name"] == "Dossiers"
    assert hits[0]["score"] > 0 and hits[0]["input_schema"] and hits[0]["available"] is True


async def test_an_empty_search_finds_nothing_and_the_list_is_the_one_by_name(client, remote, embeddings):
    remote.listed = catalogue()
    await add_server(client)

    assert await search(client, "") == [] and await search(client, "   ") == []
    assert len((await client.get("/api/tools")).json()) > 20


async def test_a_search_answers_with_at_most_the_limit_and_the_limit_is_capped(client, remote, embeddings, monkeypatch):
    monkeypatch.setattr(tool_search_service._settings, "TOOLS_SEARCH_LIMIT", 4)
    remote.listed = [RemoteTool(f"change_{i}", "Convertit une devise", SCHEMA, False) for i in range(12)]
    await add_server(client)

    assert len(await search(client, "devise")) == 4
    assert len(await search(client, "devise", limit=2)) == 2
    assert len(await search(client, "devise", limit=500)) == 4


async def test_a_few_tools_are_searched_on_their_words_without_the_index(client, remote, embeddings):
    await add_server(client)  # two tools, plus Muffin's own: fewer than the index needs
    imported = len(embeddings.calls)

    hits = await search(client, "cherche un dossier")

    assert names(hits)[:1] == ["chercher"] and {hit["match"] for hit in hits} == {"lexical"}
    assert len(embeddings.calls) == imported  # the search itself called no model


# --- the rights come first ---


async def test_a_tool_of_a_server_the_person_cannot_see_is_never_returned_nor_its_existence_given_away(
    client, remote, embeddings
):
    become(BOB)
    remote.listed = catalogue() + [
        RemoteTool("dossier_rh_confidentiel", "Dossier personnel des agents du SI RH", SCHEMA, False)
    ]
    await add_server(client, "SI RH secret")
    become(ALICE)
    remote.listed = catalogue()
    await add_server(client, "Alice")

    for query in ("dossier personnel agents", "SI RH confidentiel", "dossier_rh_confidentiel"):
        found = await search(client, query)
        assert "dossier_rh_confidentiel" not in json.dumps(found) and "SI RH secret" not in json.dumps(found)
        assert all(hit["server_name"] in (None, "Alice") for hit in found)
    assert "dossier_rh_confidentiel" not in json.dumps((await client.get("/api/tools")).json())


async def test_a_tool_of_a_server_shared_with_a_group_is_found_by_its_members_only(client, remote, embeddings):
    become(BOB, ["rh"])
    remote.listed = catalogue()
    await add_server(client, "RH", visibility="groups", group_ids=["rh"])

    become(CARL, ["rh"])
    member = await search(client, "quelle monnaie pour ce change ?")
    become(ALICE, [])
    outsider = await search(client, "quelle monnaie pour ce change ?")

    assert names(member)[:1] == ["convertir"] and "convertir" not in names(outsider)


async def test_a_server_that_is_switched_off_or_deleted_returns_no_tool(client, remote, embeddings):
    remote.listed = catalogue()
    server = await add_server(client)
    assert names(await search(client, "quelle monnaie pour ce change ?"))[:1] == ["convertir"]

    await client.patch(f"/api/tool-servers/{server['id']}", json={"enabled": False})
    switched_off = await search(client, "quelle monnaie pour ce change ?")
    await client.patch(f"/api/tool-servers/{server['id']}", json={"enabled": True})
    await client.delete(f"/api/tool-servers/{server['id']}")
    deleted = await search(client, "quelle monnaie pour ce change ?")

    assert "convertir" not in names(switched_off) and "convertir" not in names(deleted)


async def test_a_tool_a_conversation_removed_is_shown_as_removed_and_never_given_to_the_model(
    client, remote, embeddings
):
    remote.listed = catalogue()
    server = await add_server(client)
    run_id, conversation_id = await make_run()
    await ask(run_id, "quelle monnaie pour ce change ?")
    await client.put(
        f"/api/conversations/{conversation_id}/tools", json={"disabled_refs": [ref_of(server, "convertir")]}
    )

    shown = await search(client, "quelle monnaie pour ce change ?", conversation_id=str(conversation_id))
    given = await _definitions(client, run_id)

    assert [hit["available"] for hit in shown if hit["name"] == "convertir"] == [False]
    assert "convertir" not in names(given)


# --- what the model is given ---


async def test_with_many_tools_the_model_is_given_the_closest_ones_and_muffins_own(client, remote, embeddings):
    remote.listed = catalogue()
    await add_server(client)
    run_id, _ = await make_run()
    await ask(run_id, "Convertis 100 euros : quelle monnaie et quel change ?")

    given = await _definitions(client, run_id)

    remote_names = [tool["name"] for tool in given if tool["server_id"]]
    assert "convertir" in remote_names and len(remote_names) <= tool_search_service._settings.TOOLS_SELECTED_MAX
    assert {"calculatrice", "calcul_dates"} <= set(names(given))  # Muffin's own are always there


async def test_each_question_gets_the_tools_it_needs_and_the_definitions_are_much_shorter(client, remote, embeddings):
    remote.listed = catalogue()
    await add_server(client)
    everything = json.dumps((await client.get("/api/tools")).json())
    questions = {
        "Quel est le taux de change de cette monnaie ?": "convertir",
        "Retrouve le dossier personnel de cet agent": "fiche_agent",
        "Quelle température et quelle pluie demain ?": "previsions",
    }

    for question, wanted in questions.items():
        run_id, _ = await make_run()
        await ask(run_id, question)
        given = await _definitions(client, run_id)

        assert wanted in names(given)
        assert len(json.dumps(given)) < len(everything) / 2  # the tokens of the definitions, before and after


async def test_a_question_that_says_nothing_about_any_tool_keeps_the_list_bounded_as_it_was(client, remote, embeddings):
    remote.listed = catalogue()
    await add_server(client)
    run_id, _ = await make_run()
    await ask(run_id, "zzz qqq")

    given = await _definitions(client, run_id)

    assert len([tool for tool in given if tool["server_id"]]) == tool_search_service._settings.TOOLS_SELECTED_MAX


async def test_up_to_the_maximum_the_model_is_given_every_tool_with_no_search(client, remote, embeddings):
    await add_server(client)  # two tools: no choice to make
    imported = len(embeddings.calls)
    run_id, _ = await make_run()
    await ask(run_id, "quelle monnaie ?")

    assert names(await _definitions(client, run_id)) == ["calculatrice", "calcul_dates", "chercher", "supprimer"]
    assert len(embeddings.calls) == imported  # nothing was embedded to choose


# --- when the embedding model or the index is down ---


async def test_with_the_embedding_model_down_the_chat_goes_on_and_the_interface_matches_the_words(
    client, remote, embeddings, monkeypatch
):
    remote.listed = catalogue()
    await add_server(client)

    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    run_id, _ = await make_run()
    await ask(run_id, "Convertis cette devise")
    given = await _definitions(client, run_id)
    found = await search(client, "devise")

    assert "convertir" in names(given) and names(found)[:1] == ["convertir"]
    assert {hit["match"] for hit in found} == {"lexical"}


async def test_with_the_index_down_the_chat_goes_on(client, remote, embeddings, monkeypatch):
    remote.listed = catalogue()
    await add_server(client)

    def down(*_args, **_kwargs):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(vector_store, "search_tools", down)
    run_id, _ = await make_run()
    await ask(run_id, "Convertis cette devise")

    assert "convertir" in names(await _definitions(client, run_id))
    assert (await client.get("/api/tools/search", params={"q": "devise"})).status_code == 200


async def test_a_server_is_added_even_when_the_embedding_model_is_down(client, remote, embeddings, monkeypatch):
    async def down(model, input):  # noqa: A002
        raise RuntimeError("hub down")

    monkeypatch.setattr(embeddings, "create", down)
    remote.listed = catalogue()

    server = await add_server(client)

    assert len(server["tools"]) == 30 and server["last_error"] is None


# --- the index follows the server ---


async def test_the_tools_are_embedded_when_imported_and_a_synchronisation_with_no_change_embeds_nothing(
    client, remote, embeddings
):
    remote.listed = catalogue()
    server = await add_server(client)
    imported = len(embeddings.calls)
    ids = [point_id(tool["ref"]) for tool in server["tools"]]

    await client.post(f"/api/tool-servers/{server['id']}/sync")

    assert imported == 1 and len(embeddings.calls) == imported
    assert len(vector_store.get_tool_points(ids)) == 30


async def test_a_description_that_changes_is_embedded_again_and_the_result_changes(client, remote, embeddings):
    remote.listed = catalogue()
    server = await add_server(client)
    before = names(await search(client, "quelle température demain ?"))[:1]
    embeddings.calls.clear()

    remote.listed = [
        CURRENCY,
        PERSONNEL,
        RemoteTool("previsions", "Convertit un montant : taux de change", SCHEMA, False),
    ] + [RemoteTool(f"outil_{i}", "Sans rapport avec les sujets", SCHEMA, False) for i in range(27)]
    await client.post(f"/api/tool-servers/{server['id']}/sync")
    after_change = await search(client, "quelle température demain ?")

    assert before == ["previsions"]
    assert [len(call) for call in embeddings.calls][:1] == [1]  # only the tool that changed
    assert "previsions" not in names(after_change)[:1]


async def test_the_points_of_the_tools_a_server_no_longer_lists_and_of_a_deleted_server_are_removed(
    client, remote, embeddings
):
    remote.listed = catalogue()
    server = await add_server(client)
    refs = {tool["name"]: point_id(tool["ref"]) for tool in server["tools"]}

    remote.listed = [CURRENCY]
    await client.post(f"/api/tool-servers/{server['id']}/sync")
    left = set(vector_store.get_tool_points(list(refs.values())))
    await client.delete(f"/api/tool-servers/{server['id']}")

    assert left == {refs["convertir"]} and vector_store.get_tool_points(list(refs.values())) == {}


async def test_a_description_is_indexed_cut_whatever_a_server_writes(client, remote, embeddings):
    remote.listed = [RemoteTool("long", "a" * 5000, SCHEMA, False)]

    await add_server(client)

    assert max(len(t) for call in embeddings.calls for t in call) <= tool_search_service._MAX_TEXT_CHARS
