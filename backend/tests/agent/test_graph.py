"""The paths of the graph and what each costs in model calls: one call decides (`plan`), the research is code, one call
writes the answer."""

import json
from typing import Any

import pytest

from tests.agent.conftest import initial_state

HR = {"id": "col-hr", "name": "Procédures RH", "description": "Congés, arrivée des agents", "parent_id": None}
IT = {"id": "col-it", "name": "Support IT", "description": "Postes de travail, comptes", "parent_id": None}
VDBS = [HR, IT]


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def router(plan: dict | None = None, *, answer: str = "Réponse de recherche.", grounding: dict | None = None):
    """The planner answers `plan`, the answer is `answer`, the check of the claims `grounding`."""

    def _router(system_prompt: str) -> str:
        if "You are the planner" in system_prompt:
            return json.dumps(plan or {"mode": "search"})
        if "help of Muffin" in system_prompt:
            return "Voici comment faire."
        if "Check whether every important factual claim" in system_prompt:
            return json.dumps(grounding or {"valid": True, "unsupported_claims": []})
        return answer

    return _router


async def run(make_run, query: str, plan: dict | None = None, vdbs=VDBS, **state_kwargs: Any):
    graph, fake = make_run(vdbs, router(plan))
    state = initial_state(query, **state_kwargs)
    return (await graph.ainvoke(state, config=_config(state))), fake


def planner_calls(fake) -> list:
    return [c for c in fake.llm_calls if "You are the planner" in c[0]["content"]]


# -- the cost of each path ------------------------------------------------------------------------


async def test_a_greeting_is_answered_by_the_plan_alone_with_one_model_call(make_run):
    result, fake = await run(make_run, "Bonjour !", {"mode": "direct", "answer": "Bonjour, que puis-je pour vous ?"})

    assert result["answer"] == "Bonjour, que puis-je pour vous ?" and result["citations"] == []
    assert len(fake.llm_calls) == 1
    assert fake.searched_collection_ids == []


async def test_a_simple_question_costs_two_model_calls_the_plan_and_the_answer(make_run):
    result, fake = await run(make_run, "Combien de jours de congés ?", {"mode": "search", "collections": ["col-hr"]})

    assert result["answer"] == "Réponse de recherche."
    assert len(fake.llm_calls) == 2
    assert "You are the planner" in fake.llm_calls[0][0]["content"]
    assert "Answer the user's query" in fake.llm_calls[1][0]["content"]


async def test_a_help_question_costs_two_model_calls_and_searches_nothing(make_run):
    result, fake = await run(make_run, "Comment je partage une collection ?", {"mode": "help"})

    assert result["answer"] == "Voici comment faire."
    assert len(fake.llm_calls) == 2 and fake.searched_collection_ids == []


async def test_a_request_to_clarify_ends_the_run_on_the_questions_with_one_model_call(make_run):
    questions = [
        {"question": "Quelle période ?", "header": "Période", "options": [{"label": "2024"}, {"label": "2025"}]}
    ]

    result, fake = await run(make_run, "Les chiffres ?", {"mode": "clarify", "questions": questions})

    assert result["questions"] and result["questions"][0]["question"] == "Quelle période ?"
    assert "Quelle période ?" in result["answer"]
    assert len(fake.llm_calls) == 1 and fake.searched_collection_ids == []


async def test_nobody_to_ask_means_the_run_carries_on_and_says_it_assumes(make_run):
    result, fake = await run(
        make_run,
        "Les chiffres ?",
        {"mode": "clarify", "questions": [{"question": "Quelle période ?", "options": []}]},
        interactive=False,
    )

    assert not result["questions"] and result["must_assume"] is True
    assert fake.searched_collection_ids  # it searched anyway
    assert "Begin the answer with one short sentence stating them" in fake.llm_calls[-1][1]["content"]


async def test_a_question_asked_too_often_in_a_row_is_not_asked_again(make_run):
    result, _ = await run(
        make_run, "Les chiffres ?", {"mode": "clarify", "questions": [{"question": "Quoi ?"}]}, question_rounds=2
    )

    assert not result["questions"] and result["must_assume"] is True


# -- where the research goes ----------------------------------------------------------------------


async def test_the_search_goes_to_the_collections_the_plan_chose_and_the_ones_below_them(make_run):
    _, fake = await run(make_run, "Combien de jours de congés ?", {"mode": "search", "collections": ["col-hr"]})

    assert fake.searched_collection_ids == [["col-hr"]]
    assert fake.searched_with_descendants == [True]


async def test_without_a_choice_of_the_plan_every_accessible_collection_is_searched(make_run):
    _, fake = await run(make_run, "Combien de jours de congés ?", {"mode": "search", "collections": []})

    assert fake.searched_collection_ids == [["col-hr", "col-it"]]


async def test_an_id_the_plan_made_up_is_never_searched(make_run):
    _, fake = await run(make_run, "Combien ?", {"mode": "search", "collections": ["col-hr", "col-secret"]})

    assert fake.searched_collection_ids == [["col-hr"]]


async def test_the_collections_the_user_attached_are_searched_on_top_of_the_plans(make_run):
    _, fake = await run(make_run, "Combien ?", {"mode": "search", "collections": ["col-hr"]}, pinned_vdb_ids=["col-it"])

    assert fake.searched_collection_ids == [["col-hr", "col-it"]]


async def test_a_pinned_collection_the_user_cannot_read_is_not_searched(make_run):
    _, fake = await run(make_run, "Combien ?", {"mode": "search"}, pinned_vdb_ids=["col-secret"])

    assert all("col-secret" not in ids for ids in fake.searched_collection_ids)


async def test_the_independent_queries_of_a_comparison_are_searched_in_parallel_with_no_extra_model_call(make_run):
    plan = {
        "mode": "search",
        "complexity": "complex",
        "queries": [{"query": "congés cadres", "tool": "search"}, {"query": "congés agents", "tool": "search"}],
    }

    result, fake = await run(make_run, "Compare les congés des cadres et des agents", plan)

    assert len(fake.searched_collection_ids) == 2
    assert len(fake.llm_calls) == 2  # still the plan and the answer
    assert result["needs_grounding"] is True


async def test_the_plan_is_never_told_about_the_web_unless_the_user_enabled_it(make_run):
    plan = {"mode": "search", "queries": [{"query": "actualité", "tool": "web_search"}]}
    graph, fake = make_run(VDBS, router(plan), web_results=[{"url": "https://x.test", "title": "T", "content": "C"}])
    state = initial_state("Quoi de neuf ?", web_search_enabled=False)

    await graph.ainvoke(state, config=_config(state))

    # Neither offered to the model, nor run when it names the tool anyway: the plan turns it into a plain search.
    assert '"web_search"' not in fake.llm_calls[0][0]["content"]
    assert fake.searxng.queries == [] and fake.searched_collection_ids


async def test_the_web_is_searched_when_the_user_enabled_it(make_run):
    plan = {"mode": "search", "queries": [{"query": "actualité", "tool": "web_search"}]}
    graph, fake = make_run(VDBS, router(plan), web_results=[{"url": "https://x.test", "title": "T", "content": "C"}])
    state = initial_state("Quoi de neuf ?", web_search_enabled=True)

    await graph.ainvoke(state, config=_config(state))

    assert fake.searxng.queries == ["actualité"]


# -- the gate and the widening --------------------------------------------------------------------


async def test_nothing_found_in_the_chosen_collections_widens_the_search_to_all_of_them_once(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search", "collections": ["col-hr"]}))
    seen = []
    original = fake.search

    async def search(collection_ids, query, limit, include_descendants=False):
        seen.append(list(collection_ids))
        return [] if collection_ids == ["col-hr"] else await original(collection_ids, query, limit, include_descendants)

    fake.search = search
    state = initial_state("Un poste de travail ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert seen == [["col-hr"], ["col-hr", "col-it"]]
    assert result["widened"] is True and len(result["deduped_evidence"]) == 2
    assert len(fake.llm_calls) == 2  # widening costs no model call


async def test_nothing_found_anywhere_answers_that_nothing_was_found_without_asking_the_model(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search", "collections": []}))

    async def nothing(*args, **kwargs):
        return []

    fake.search = nothing
    state = initial_state("Introuvable ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert "couldn't find any relevant information" in result["answer"]
    assert len(fake.llm_calls) == 1  # the plan only
    assert result["coverage_result"]["status"] == "insufficient"


async def test_a_lookup_of_the_knowledge_base_needs_no_passage_to_be_enough(make_run):
    plan = {"mode": "search", "queries": [{"query": "combien de collections ?", "tool": "list_collections"}]}

    result, _ = await run(make_run, "Combien de collections ai-je ?", plan)

    assert result["coverage_result"]["status"] == "sufficient"


# -- the guards -----------------------------------------------------------------------------------


async def test_a_run_cancelled_before_it_starts_stops_without_calling_the_model(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.cancel_requested = True
    state = initial_state("Combien ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert fake.llm_calls == [] and result["execution_status"] == "cancelled"


async def test_an_unusable_plan_is_a_plain_search_of_the_question(make_run):
    graph, fake = make_run(VDBS, lambda prompt: "ceci n'est pas du JSON" if "You are the planner" in prompt else "Oui.")
    state = initial_state("Combien de jours ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert result["answer"] == "Oui." and fake.searched_collection_ids == [["col-hr", "col-it"]]


async def test_the_plan_is_shown_the_last_turns_and_the_collections_not_the_whole_history(make_run):
    history = [{"role": "user", "content": f"ancien {i}"} for i in range(20)]
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    state = initial_state("Et pour les cadres ?", history=history)

    await graph.ainvoke(state, config=_config(state))

    prompt = planner_calls(fake)[0][1]["content"]
    assert "ancien 19" in prompt and "ancien 0" not in prompt
    assert "id" in prompt and "Procédures RH" in prompt and "Support IT" in prompt


async def test_a_big_catalogue_is_narrowed_by_the_vector_prefilter_without_a_model(make_run):
    many = [{"id": f"c{i}", "name": f"Collection {i}", "description": "", "parent_id": None} for i in range(30)]
    graph, fake = make_run(many, router({"mode": "search"}))
    fake.collection_search_hits = [{"collection_id": "c3"}, {"collection_id": "c7"}]
    state = initial_state("Un sujet précis ?")

    await graph.ainvoke(state, config=_config(state))

    prompt = planner_calls(fake)[0][1]["content"]
    assert "Collection 3" in prompt and "Collection 7" in prompt and "Collection 12" not in prompt
    assert len(fake.llm_calls) == 2


@pytest.mark.parametrize("mode", ["direct", "clarify", "help"])
async def test_the_modes_that_never_search_never_reach_the_research(make_run, mode):
    plan = {"mode": mode, "answer": "ok", "questions": [{"question": "?"}]}

    _, fake = await run(make_run, "Salut", plan)

    assert fake.searched_collection_ids == []


# -- the user's token, for the tools that will need it -----------------------------------------------


async def test_the_users_token_reaches_the_parallel_branches_of_the_research(make_run):
    from app.agent.user_token import current_user_token, set_user_token

    graph, fake = make_run(VDBS, router({"mode": "search", "complexity": "complex"}))
    seen = []
    original = fake.search

    async def search(collection_ids, query, limit, include_descendants=False):
        seen.append(current_user_token())
        return await original(collection_ids, query, limit, include_descendants)

    fake.search = search
    state = initial_state("Une question ?")
    set_user_token("the-users-token")
    try:
        await graph.ainvoke(state, config=_config(state))
    finally:
        set_user_token(None)

    assert seen == ["the-users-token"]


async def test_the_token_is_never_part_of_the_state_the_checkpointer_stores(make_run):
    from app.agent.user_token import set_user_token

    graph, fake = make_run(VDBS, router({"mode": "search"}))
    state = initial_state("Une question ?")
    set_user_token("the-users-token")
    try:
        result = await graph.ainvoke(state, config=_config(state))
    finally:
        set_user_token(None)

    assert "the-users-token" not in json.dumps(result, default=str)
    assert "the-users-token" not in json.dumps(graph.get_state(_config(state)).values, default=str)


# -- what the chat shows while the run goes on ---------------------------------------------------


async def test_each_step_of_a_search_is_reported_with_what_the_chat_shows_of_it(make_run):
    plan = {
        "mode": "search",
        "collections": ["col-hr"],
        "queries": [{"query": "congés des cadres", "tool": "search"}, {"query": "congés des agents", "tool": "search"}],
    }
    graph, fake = make_run(VDBS, router(plan))
    state = initial_state("Compare les congés")

    await graph.ainvoke(state, config=_config(state))

    types = [type_ for type_, _ in fake.event_data]
    assert (
        types.index("query_analysis_completed")
        < types.index("task_started")
        < types.index("coverage_evaluation_completed")
    )
    data = dict(fake.event_data[types.index("query_analysis_completed")][1]["analysis"])
    assert data["mode"] == "search" and len(data["queries"]) == 2 and data["collections"] == ["col-hr"]
    routed = [d for t, d in fake.event_data if t == "vdb_routing_completed"]
    assert [d["selected"] for d in routed] == [["Procédures RH"], ["Procédures RH"]]
    assert sorted(d["evidence_count"] for t, d in fake.event_data if t == "task_completed") == [1, 1]
    assert "answer_generation_completed" in types and "answer_context_built" in types
