"""The guardrails on the input in the graph (#516): beside `prepare` and waited for, a request that is stopped reaches
no model, no search, no web and no tool, a request that is masked is read masked by everything, and one that is checked
costs no more than it did."""

import asyncio
import json
import time

import pytest

from tests.agent.conftest import initial_state
from tests.agent.test_graph import VDBS, router

REFUSAL = "Votre demande ne peut pas être traitée."
EMAIL = "jean.dupont@example.fr"


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def decision(outcome: str, *, query: str = "", message: str | None = None, checked: int = 2, flagged: int = 1) -> dict:
    return {"outcome": outcome, "query": query, "message": message, "checked": checked, "flagged": flagged}


def events(fake) -> list[str]:
    return [type_ for type_, _ in fake.event_data]


# --- a request that goes on ---


async def test_a_request_that_passes_goes_on_to_the_plan_and_the_events_say_only_counts(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.guardrail_decision = decision("continue", checked=3, flagged=0)
    state = initial_state("Quelle est la politique de congés ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert result["answer"] == "Réponse de recherche." and result["guardrail"]["outcome"] == "continue"
    started, completed = events(fake).index("guardrail_started"), events(fake).index("guardrail_completed")
    assert started < completed and fake.guardrail_calls == [state["run_id"]]
    assert dict(fake.event_data)["guardrail_completed"] == {"outcome": "continue", "checked": 3, "flagged": 0}
    assert fake.llm_calls  # the plan and the answer were asked


async def test_a_warning_goes_on_exactly_as_a_request_that_passes(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.guardrail_decision = decision("continue_with_warning", message="Attention.")
    state = initial_state("Mon IBAN est FR76...")

    result = await graph.ainvoke(state, config=_config(state))

    assert result["answer"] == "Réponse de recherche." and result["original_query"] == "Mon IBAN est FR76..."
    assert result["guardrail"]["message"] == "Attention."


# --- a request that is stopped ---


async def test_a_request_that_is_stopped_ends_with_the_refusal_and_reaches_no_model_no_search_no_web_no_tool(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}), web_results=[{"url": "https://x.test", "title": "T"}])
    fake.guardrail_decision = decision("block", message=REFUSAL)
    # A request that would otherwise look for tools, for documents to edit, and for the web.
    state = initial_state("Modifie le document sur les congés et cherche sur le web", web_search_enabled=True)

    result = await graph.ainvoke(state, config=_config(state))

    assert result["answer"] == REFUSAL and result["citations"] == [] and result["execution_status"] == "completed"
    assert result["needs_grounding"] is False and not result.get("cancelled")
    assert fake.llm_calls == [] and fake.searched_collection_ids == [] and fake.collection_search_calls == []
    assert fake.searxng.queries == [] and getattr(fake, "tool_calls", []) == []
    assert getattr(fake, "tool_definitions_asked", 0) == 0 and fake.editable_calls == []
    assert fake.editable_collections_calls == []
    assert "guardrail_blocked" in events(fake) and "run_failed" not in events(fake)
    assert dict(fake.event_data)["guardrail_blocked"] == {"checked": 2, "flagged": 1}  # counts: not which, not why


async def test_a_stopped_request_does_not_embed_the_text_even_when_there_are_many_collections(make_run, monkeypatch):
    many = [{"id": f"c{i}", "name": f"C{i}", "description": "d", "parent_id": None} for i in range(80)]
    graph, fake = make_run(many, router({"mode": "search"}))
    fake.guardrail_decision = decision("block", message=REFUSAL)
    state = initial_state("texte qui ne doit pas être embarqué")

    await graph.ainvoke(state, config=_config(state))

    assert fake.collection_search_calls == []  # the vector pre-filter embeds the text: it was never started


# --- a request that is masked ---


async def test_a_request_that_is_masked_is_read_masked_by_every_model_call_and_never_as_it_was_written(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.guardrail_decision = decision("continue_with_redaction", query="Écris à [EMAIL] au sujet des congés")
    state = initial_state(
        f"Écris à {EMAIL} au sujet des congés", history=[{"role": "user", "content": "[Message écarté]"}]
    )

    result = await graph.ainvoke(state, config=_config(state))

    everything = json.dumps(fake.llm_calls, ensure_ascii=False) + json.dumps(result, ensure_ascii=False, default=str)
    assert EMAIL not in everything and "[EMAIL]" in everything
    assert result["original_query"] == "Écris à [EMAIL] au sujet des congés"
    assert result["messages"][-1] == {"role": "user", "content": "Écris à [EMAIL] au sujet des congés"}
    assert result["messages"][0]["content"] == "[Message écarté]"  # the turns before are not touched here


async def test_what_reads_the_text_after_the_guardrails_reads_the_masked_one(make_run):
    """`prepare` has no text to read; what does (the verbs that ask for an edit) is `prepare_request`, after them."""
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.editable_documents = [{"id": "doc-1", "name": "Congés", "collection_id": "col-hr"}]
    fake.guardrail_decision = decision("continue_with_redaction", query="Bonjour")  # the verb is gone with the text
    state = initial_state("Modifie le document, jean@example.fr")

    await graph.ainvoke(state, config=_config(state))

    assert fake.editable_calls == []


# --- in parallel, and waited for ---


async def test_the_guardrails_run_beside_the_discovery_of_collections_and_the_plan_waits_for_them(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    stamps: dict[str, float] = {}
    original_discovery = fake.list_accessible_collections

    async def slow_guardrails(run_id):
        stamps["guardrails_start"] = time.monotonic()
        await asyncio.sleep(0.3)
        stamps["guardrails_end"] = time.monotonic()
        return decision("continue", checked=1, flagged=0)

    async def discovery(user_id, groups=None):
        stamps["discovery"] = time.monotonic()
        return await original_discovery(user_id, groups)

    original_chat = fake.llm_chat

    async def chat(*args, **kwargs):
        stamps.setdefault("first_model_call", time.monotonic())
        return await original_chat(*args, **kwargs)

    fake.check_guardrails = slow_guardrails
    fake.list_accessible_collections = discovery
    fake.llm_chat = chat
    state = initial_state("Quelle est la politique de congés ?")

    started = time.monotonic()
    await graph.ainvoke(state, config=_config(state))

    assert abs(stamps["discovery"] - stamps["guardrails_start"]) < 0.1  # together, not one after the other
    assert stamps["first_model_call"] >= stamps["guardrails_end"]  # no model before the verdict
    assert time.monotonic() - started < 1.0


async def test_with_no_guardrail_the_check_adds_no_wait(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    state = initial_state("Quelle est la politique de congés ?")

    started = time.monotonic()
    await graph.ainvoke(state, config=_config(state))

    assert time.monotonic() - started < 0.5 and fake.guardrail_calls == [state["run_id"]]


# --- cancelling, failing ---


async def test_a_cancelled_run_does_not_ask_the_guardrails(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.cancel_requested = True
    state = initial_state("bonjour")

    result = await graph.ainvoke(state, config=_config(state))

    assert result["cancelled"] is True and getattr(fake, "guardrail_calls", []) == [] and fake.llm_calls == []


async def test_a_check_that_cannot_be_made_is_not_a_check_that_passed_the_run_fails(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))

    async def broken(run_id):
        raise RuntimeError("the backend is down")

    fake.check_guardrails = broken
    state = initial_state("bonjour")

    with pytest.raises(RuntimeError):
        await graph.ainvoke(state, config=_config(state))

    assert fake.llm_calls == []
