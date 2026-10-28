import json

from app.config import settings
from tests.conftest import initial_state


def _config(state: dict) -> dict:
    return {"configurable": {"thread_id": state["run_id"]}}


def _analysis(**overrides) -> str:
    base = {
        "intent": "lookup",
        "topics": [],
        "requires_multiple_sources": False,
        "complexity": "simple",
        "ambiguous": False,
        "clarification_question": None,
    }
    base.update(overrides)
    return json.dumps(base)


def _hr_eng_vdbs() -> list[dict]:
    return [
        {
            "id": "hr",
            "name": "HR",
            "description": "HR policies",
            "tags": [],
            "document_count": 3,
        },
        {
            "id": "eng",
            "name": "Engineering",
            "description": "Engineering docs",
            "tags": [],
            "document_count": 5,
        },
    ]


def test_simple_query_runs_a_single_task(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "The policy is X [abc]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["task-1"]
    assert result["answer"] == "The policy is X [abc]."
    # A simple single-fact lookup skips the grounding check entirely (§ optimize latency) -
    # see after_generate_answer.
    assert result["grounding_result"] is None
    # Citations carry enough to link back to the source (§ sources panel: document vs tool
    # cards) - a "search" citation must resolve to a real document page and its exact chunk text.
    citation = result["citations"][0]
    assert citation["tool"] == "search"
    assert citation["page_number"] == 3
    assert citation["document_id"]
    assert citation["chunk_id"]
    assert citation["content"]
    assert citation["query"] == "What is the leave policy?"


def test_complex_query_fans_out_independent_tasks_in_parallel(make_run):
    def router(system_prompt: str) -> str:
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {"id": "telework", "query": "telework policy", "dependencies": []},
                    {"id": "leave", "query": "leave policy", "dependencies": []},
                    {"id": "benefits", "query": "benefits", "dependencies": []},
                ]
            )
        if "Analyze the user" in system_prompt:
            return _analysis(requires_multiple_sources=True, complexity="complex")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Combined answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("Compare telework, leave and benefits policies")
    result = graph.invoke(state, config=_config(state))

    assert set(result["completed_task_ids"]) == {"telework", "leave", "benefits"}
    # One evidence item per task, all preserved through the fan-in reducer (§16/§26) - none of
    # the three parallel branches' results were overwritten by the others.
    assert len(result["deduped_evidence"]) == 3
    assert {e["task_id"] for e in result["deduped_evidence"]} == {
        "telework",
        "leave",
        "benefits",
    }


def test_dependent_task_only_runs_after_its_dependencies_complete(make_run):
    task_start_order: list[str] = []

    def router(system_prompt: str) -> str:
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {"id": "a", "query": "topic a", "dependencies": []},
                    {"id": "b", "query": "topic b", "dependencies": []},
                    {"id": "c", "query": "compare a and b", "dependencies": ["a", "b"]},
                ]
            )
        if "Analyze the user" in system_prompt:
            return _analysis(requires_multiple_sources=True, complexity="complex")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)

    original_add_run_event = fake.add_run_event

    def recording_add_run_event(run_id, type_, data=None, task_id=None):  # noqa: ANN001
        if type_ == "task_started" and task_id:
            task_start_order.append(task_id)
        return original_add_run_event(run_id, type_, data, task_id)

    fake.add_run_event = recording_add_run_event

    state = initial_state("Compare a and b")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["a", "b", "c"] or sorted(result["completed_task_ids"]) == ["a", "b", "c"]
    assert task_start_order.index("c") > task_start_order.index("a")
    assert task_start_order.index("c") > task_start_order.index("b")


def test_vdb_routing_never_escapes_accessible_set(make_run):
    """§4/§12/§36 - only HR is accessible; even if the router's own JSON tried to select
    Finance, the intersection in select_relevant_vdbs must drop it."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr", "finance"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert all(e["vdb_id"] == "hr" for e in result["deduped_evidence"])
    for collection_ids in fake.searched_collection_ids:
        assert "finance" not in collection_ids


def test_web_search_runs_when_enabled_and_planner_picks_it(make_run):
    def router(system_prompt: str) -> str:
        if "Break the user's query" in system_prompt:
            assert "web_search" in system_prompt  # only offered to the planner when enabled
            return json.dumps(
                [
                    {
                        "id": "task-1",
                        "query": "current weather in Paris",
                        "dependencies": [],
                    }
                ]
            )
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta", complexity="complex")
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "It's sunny [x]."

    # decompose_query's own sanitizer falls back to "search" for any tool name outside the
    # (dynamically enabled) valid set - a hardcoded literal here proves the planner really did
    # choose "web_search" and it wasn't silently downgraded.
    import app.graph.nodes.decompose_query as decompose_query_module

    original_sanitize = decompose_query_module._sanitize

    def sanitize_with_web_search(raw, original_query, web_search_enabled):
        for item in raw:
            item["tool"] = "web_search"
        return original_sanitize(raw, original_query, web_search_enabled)

    decompose_query_module._sanitize = sanitize_with_web_search
    try:
        graph, fake = make_run(
            [],
            router,
            web_results=[
                {
                    "title": "Paris weather",
                    "url": "https://example.com/paris-weather",
                    "content": "Sunny, 22°C",
                }
            ],
        )
        state = initial_state("What's the weather in Paris right now?", web_search_enabled=True)
        result = graph.invoke(state, config=_config(state))
    finally:
        decompose_query_module._sanitize = original_sanitize

    assert fake.searxng.queries == ["current weather in Paris"]
    assert len(result["deduped_evidence"]) == 1
    evidence = result["deduped_evidence"][0]
    assert evidence["source_id"] == "https://example.com/paris-weather"
    assert evidence["metadata"]["tool"] == "web_search"
    assert result["citations"][0]["url"] == "https://example.com/paris-weather"


def test_web_search_tool_is_never_offered_to_the_planner_when_disabled(make_run):
    def router(system_prompt: str) -> str:
        if "Break the user's query" in system_prompt:
            assert "web_search" not in system_prompt
            return json.dumps(
                [
                    {
                        "id": "task-1",
                        "query": "current weather in Paris",
                        "dependencies": [],
                    }
                ]
            )
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta", complexity="complex")
        if "Decide whether" in system_prompt:
            return json.dumps(
                {
                    "status": "insufficient",
                    "missing_information": ["weather"],
                    "reasoning": "n/a",
                }
            )
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "I don't have that information [x]."

    graph, fake = make_run(
        [],
        router,
        web_results=[{"title": "Should never be reached", "url": "https://x"}],
    )
    state = initial_state("What's the weather in Paris right now?", web_search_enabled=False)
    graph.invoke(state, config=_config(state))

    assert fake.searxng.queries == []


def test_web_search_runner_refuses_even_if_the_planner_somehow_picks_it_while_disabled(
    make_run,
):
    """Defense in depth (decompose_query._sanitize is the first gate, this is the second,
    independent one) - a stale/malformed task claiming "web_search" must never actually call
    out to the web on a run that didn't opt in."""
    import app.graph.nodes.decompose_query as decompose_query_module

    original_sanitize = decompose_query_module._sanitize

    def sanitize_forcing_web_search(raw, original_query, web_search_enabled):
        for item in raw:
            item["tool"] = "web_search"
        return original_sanitize(raw, original_query, True)  # force it past the first gate

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()  # simple/non-meta: decompose_query short-circuits without an LLM call
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "No evidence to answer from."

    decompose_query_module._sanitize = sanitize_forcing_web_search
    try:
        graph, fake = make_run([], router, web_results=[])
        state = initial_state("anything", web_search_enabled=False)
        result = graph.invoke(state, config=_config(state))
    finally:
        decompose_query_module._sanitize = original_sanitize

    assert fake.searxng.queries == []
    assert result["deduped_evidence"] == []


def test_evaluate_coverage_does_not_wave_through_a_web_search_result_as_meta_complete(
    make_run,
):
    """Guards the evaluate_coverage.py fix directly: a run whose *only* completed task is
    web_search must still get a real LLM sufficiency judgment, not the is_meta_only shortcut
    meant for list_collections/collection_summary/list_documents/page_content."""
    import app.graph.nodes.decompose_query as decompose_query_module

    original_sanitize = decompose_query_module._sanitize

    def force_web_search(raw, original_query, web_search_enabled):
        for item in raw:
            item["tool"] = "web_search"
        return original_sanitize(raw, original_query, web_search_enabled)

    decompose_query_module._sanitize = force_web_search

    coverage_prompts: list[str] = []

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "Decide whether" in system_prompt:
            coverage_prompts.append(system_prompt)
            return json.dumps(
                {
                    "status": "insufficient",
                    "missing_information": ["more detail"],
                    "reasoning": "n/a",
                }
            )
        if "Coverage of a research query was judged insufficient" in system_prompt:
            return json.dumps([])
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Partial answer [x]."

    try:
        graph, fake = make_run(
            [],
            router,
            web_results=[{"title": "Result", "url": "https://example.com/r", "content": "..."}],
        )
        state = initial_state("anything", web_search_enabled=True)
        result = graph.invoke(state, config=_config(state))
    finally:
        decompose_query_module._sanitize = original_sanitize

    # evaluate_coverage actually called the LLM (the is_meta_only shortcut never calls it at
    # all) and its "insufficient" verdict survived into the final result.
    assert len(coverage_prompts) >= 1
    assert result["coverage_result"]["status"] == "insufficient"


def test_accessible_vdbs_lookup_forwards_the_run_s_user_groups(make_run):
    """load_accessible_vdbs must thread state["user_groups"] through to the backend so a
    collection shared to one of the user's Keycloak groups is part of the accessible set, not
    just owner/public/direct-share collections (see CollectionRepository.list_all_accessible).
    """

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the leave policy?", user_groups=["/hr-team"])
    graph.invoke(state, config=_config(state))

    assert fake.accessible_collections_groups_requested == [["/hr-team"]]


def test_pinned_collections_are_always_searched_even_if_not_llm_selected(make_run):
    """The chat composer's "+" picker - a user-attached collection is searched regardless of
    what VDB routing's own relevance guess would have picked on its own."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'  # the LLM itself would only have picked HR
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What is the leave policy?", pinned_vdb_ids=["eng"])
    graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == [["hr", "eng"]]


def test_multi_vdb_task_searches_all_relevant_vdbs_in_parallel(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr", "eng"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("cross-team policy question")
    result = graph.invoke(state, config=_config(state))

    vdb_ids = {e["vdb_id"] for e in result["deduped_evidence"]}
    assert vdb_ids == {"hr", "eng"}


def test_failure_in_one_task_does_not_fail_the_others(make_run, monkeypatch):
    def router(system_prompt: str) -> str:
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {"id": "ok", "query": "ok topic", "dependencies": []},
                    {"id": "bad", "query": "bad topic", "dependencies": []},
                ]
            )
        if "Analyze the user" in system_prompt:
            return _analysis(requires_multiple_sources=True, complexity="complex")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)

    real_search = fake.search

    def flaky_search(collection_ids, query, limit):  # noqa: ANN001
        if "bad" in query:
            raise RuntimeError("search backend exploded")
        return real_search(collection_ids, query, limit)

    fake.search = flaky_search

    state = initial_state("two-topic query, one will fail")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["ok"]
    assert result["failed_task_ids"] == ["bad"]
    assert result["answer"] == "answer [x]."


def _insufficient_router(calls=None):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "insufficient", "missing_information": ["2025 update"], "reasoning": "stale"})
        if "do not contain enough to answer" in system_prompt:
            if calls is not None:
                calls["clarify"] += 1
            return json.dumps(
                {
                    "questions": [
                        {
                            "question": "Which policy do you mean?",
                            "header": "Policy",
                            "multi_select": False,
                            "options": [
                                {"label": "Leave", "description": "Paid leave"},
                                {"label": "Remote", "description": "Remote work"},
                            ],
                        }
                    ]
                }
            )
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    return router


def test_insufficient_coverage_asks_the_user_instead_of_replanning(make_run):
    calls = {"clarify": 0}
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _insufficient_router(calls))
    state = initial_state("What is the current leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert calls["clarify"] == 1
    assert result["questions"][0]["options"][0]["label"] == "Leave"
    assert "Which policy do you mean?" in result["answer"]
    assert result["replan_count"] == 0
    assert [data for type_, data in fake.event_data if type_ == "clarification_requested"]


def test_insufficient_coverage_answers_with_assumptions_when_nobody_can_be_asked(make_run):
    calls = {"clarify": 0}
    graph, _fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _insufficient_router(calls))
    state = initial_state("What is the current leave policy?", interactive=False)
    result = graph.invoke(state, config=_config(state))

    assert calls["clarify"] == 0
    assert not result.get("questions")
    assert result["answer"] == "answer [x]."


def test_insufficient_coverage_answers_once_the_cap_on_questions_is_reached(make_run):
    calls = {"clarify": 0}
    graph, _fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _insufficient_router(calls))
    state = initial_state("What is the current leave policy?", question_rounds=settings.MAX_QUESTION_ROUNDS)
    result = graph.invoke(state, config=_config(state))

    assert calls["clarify"] == 0
    assert result["answer"] == "answer [x]."


def test_grounding_failure_triggers_targeted_research(make_run):
    calls = {"grounding": 0}

    def router(system_prompt: str) -> str:
        # complexity="complex" - a simple single-fact lookup now skips grounding entirely (§
        # optimize latency), and this test is specifically about the grounding loop.
        if "Analyze the user" in system_prompt:
            return _analysis(complexity="complex")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            calls["grounding"] += 1
            if calls["grounding"] == 1:
                return json.dumps({"valid": False, "unsupported_claims": ["unsupported date claim"]})
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer with a claim [x]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert result["grounding_research_count"] == 1
    assert result["grounding_result"]["valid"] is True
    assert any(task_id.startswith("grounding-1-") for task_id in result["completed_task_ids"])


_OPTIONS = [
    {
        "question": "Which department do you mean?",
        "header": "Department",
        "multi_select": False,
        "options": [{"label": "HR", "description": "People"}, {"label": "Finance", "description": ""}],
    }
]


def _clarification_router(**analysis):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(ambiguous=True, **analysis)
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    return router


def test_ambiguous_query_ends_the_run_on_the_questions_with_options(make_run):
    router = _clarification_router(questions=_OPTIONS, clarification_question="Which department?")
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the policy?")

    result = graph.invoke(state, config=_config(state))

    assert "__interrupt__" not in result
    assert result["questions"] == _OPTIONS
    assert result["answer"] == "Which department do you mean?\n- HR : People\n- Finance"
    assert result["citations"] == []
    requested = [data for type_, data in fake.event_data if type_ == "clarification_requested"]
    assert requested[0]["questions"] == _OPTIONS
    assert requested[0]["question"] == result["answer"]


def test_a_question_without_valid_options_falls_back_on_the_free_text_question(make_run):
    router = _clarification_router(
        questions=[{"question": "Which?", "options": [{"label": "only one"}]}],
        clarification_question="Which department do you mean?",
    )
    graph, _ = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the policy?")

    result = graph.invoke(state, config=_config(state))

    assert [(q["question"], q["options"]) for q in result["questions"]] == [("Which department do you mean?", [])]
    assert result["answer"] == "Which department do you mean?"


def test_a_run_nobody_can_answer_carries_on_and_states_its_assumptions(make_run):
    router = _clarification_router(questions=_OPTIONS)
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the policy?", interactive=False)

    result = graph.invoke(state, config=_config(state))

    assert not result.get("questions")
    assert result["answer"] == "answer [x]."
    assert not [type_ for type_, _ in fake.events if type_ == "clarification_requested"]


def test_the_assistant_stops_asking_after_too_many_rounds_in_a_row(make_run):
    router = _clarification_router(questions=_OPTIONS)
    graph, _ = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the policy?", question_rounds=2)

    result = graph.invoke(state, config=_config(state))

    assert not result.get("questions")
    assert result["answer"] == "answer [x]."


def test_a_run_that_carries_on_without_asking_tells_the_model_to_state_its_assumptions(make_run):
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _clarification_router())
    state = initial_state("What is the policy?", interactive=False)

    graph.invoke(state, config=_config(state))

    prompt = next(call for call in fake.llm_calls if "Answer the user's query" in call[0]["content"])[1]["content"]
    assert "Nobody can answer questions here" in prompt


def test_a_run_that_could_ask_does_not_mention_assumptions(make_run):
    graph, fake = make_run(
        [{"id": "hr", "name": "HR", "description": "HR", "tags": []}],
        lambda prompt: _analysis() if "Analyze the user" in prompt else "answer [x].",
    )
    state = initial_state("What is the policy?")

    graph.invoke(state, config=_config(state))

    assert not any("Nobody can answer" in call[-1]["content"] for call in fake.llm_calls)


def test_the_analysis_prompt_asks_for_questions_whichever_version_of_it_is_active(make_run):
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _clarification_router())
    state = initial_state("What is the policy?")

    graph.invoke(state, config=_config(state))

    system_prompt = next(call for call in fake.llm_calls if "Analyze the user" in call[0]["content"])[0]["content"]
    assert '"questions"' in system_prompt and "2 to 4 options" in system_prompt


def test_list_collections_tool_answers_from_accessible_vdbs_without_searching(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "how many collections do I have",
                        "tool": "list_collections",
                    }
                ]
            )
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "You have 2 collections: HR and Engineering [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("How many collections do I have?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == []
    # One evidence item per collection, plus one explicit "you have exactly N" fact - never left
    # for the answer LLM to infer a count from prose alone (real model tested against would
    # sometimes refuse to, see test_meta_tool_never_asks_for_a_pointless_precision's sibling bug).
    assert len(result["deduped_evidence"]) == 3
    assert any(
        e["content"] == "You have exactly 2 accessible knowledge base collections." for e in result["deduped_evidence"]
    )
    assert result["answer"] == "You have 2 collections: HR and Engineering [x]."
    # Meta-tool citations are input/output only (§ sources panel: tool cards) - no page/chunk to
    # link to, since nothing was actually searched.
    assert all(c["tool"] == "list_collections" for c in result["citations"])
    assert all(c["page_number"] is None for c in result["citations"])
    assert all(c["query"] == "how many collections do I have" for c in result["citations"])


def test_meta_query_skips_grounding_check(make_run):
    """A deterministic knowledge-base lookup (counts, summaries) has nothing to hallucinate a
    *claim* about - validate_grounding is skipped entirely (§ optimize latency)."""
    grounding_calls = 0

    def router(system_prompt: str) -> str:
        nonlocal grounding_calls
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "how many collections do I have",
                        "tool": "list_collections",
                    }
                ]
            )
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            grounding_calls += 1
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "You have 2 collections [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("How many collections do I have?")
    result = graph.invoke(state, config=_config(state))

    assert grounding_calls == 0, "validate_grounding must not run for a meta-only task"
    assert result["grounding_result"] is None
    assert result["answer"] == "You have 2 collections [x]."


def test_meta_tool_never_replans_into_a_pointless_search(make_run):
    """Regression: evaluate_coverage used to run its usual LLM sufficiency judgment on
    list_collections' evidence too. A collection description that doesn't literally state a
    count reads as "insufficient" to that judgment, triggering a replan into a `search` task -
    which can never answer "how many collections do I have" - burning the replan budget and
    still producing a hedged "couldn't be established" answer instead of the count already in
    hand. A meta-only task's evidence must be treated as complete without ever asking.
    """
    coverage_calls = 0

    def router(system_prompt: str) -> str:
        nonlocal coverage_calls
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "count-collections",
                        "query": "how many collections",
                        "tool": "list_collections",
                    }
                ]
            )
        if "Decide whether" in system_prompt:
            coverage_calls += 1
            # The real, observed failure mode: the LLM calls a legitimate meta answer
            # insufficient because the description doesn't literally state a count.
            return json.dumps(
                {
                    "status": "insufficient",
                    "missing_information": ["the number of collections"],
                    "reasoning": "n/a",
                }
            )
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "You have 2 collections [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("How many collections do I have?")
    result = graph.invoke(state, config=_config(state))

    assert coverage_calls == 0, "evaluate_coverage must not ask the LLM about a meta-only task's evidence"
    assert result["replan_count"] == 0
    assert result["plan_version"] == 0
    assert result["coverage_result"]["status"] == "sufficient"
    assert result["answer"] == "You have 2 collections [x]."


def test_collection_summary_tool_resolves_a_single_collection(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "summarize the HR collection",
                        "tool": "collection_summary",
                    }
                ]
            )
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What's the HR collection about?")
    result = graph.invoke(state, config=_config(state))

    assert len(result["deduped_evidence"]) == 1
    assert result["deduped_evidence"][0]["vdb_id"] == "hr"
    assert "3 document(s)" in result["deduped_evidence"][0]["content"]


def test_list_documents_tool_calls_backend_for_the_resolved_collection(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "how many documents in HR",
                        "tool": "list_documents",
                    }
                ]
            )
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "There are 2 documents [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.documents_by_collection["hr"] = [
        {
            "id": "doc-1",
            "name": "handbook.pdf",
            "status": "indexed",
            "summary": "Employee handbook.",
        },
        {
            "id": "doc-2",
            "name": "leave-policy.pdf",
            "status": "indexed",
            "summary": "Leave policy.",
        },
    ]

    state = initial_state("How many documents are in the HR collection?")
    result = graph.invoke(state, config=_config(state))

    # Two per-document evidence items, plus one explicit "has exactly N documents" fact.
    assert len(result["deduped_evidence"]) == 3
    assert {"doc-1", "doc-2"} <= {e["source_id"] for e in result["deduped_evidence"]}
    assert any(e["content"] == "The 'HR' collection has exactly 2 documents." for e in result["deduped_evidence"])
    assert fake.searched_collection_ids == []


def test_page_content_tool_resolves_document_and_page_then_fetches_it(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "page 3 of the handbook",
                        "tool": "page_content",
                    }
                ]
            )
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "identify which document and page number" in system_prompt.lower():
            return json.dumps({"document_id": "doc-1", "page_number": 3})
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Here is page 3 [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.documents_by_collection["hr"] = [
        {
            "id": "doc-1",
            "name": "handbook.pdf",
            "status": "indexed",
            "summary": "Employee handbook.",
        },
    ]
    fake.pages[("doc-1", 3)] = {
        "page_number": 3,
        "content": "Telework is allowed two days a week.",
        "screenshot_url": "https://example.com/shots/doc-1-3.png",
    }

    state = initial_state("Show me page 3 of the handbook")
    result = graph.invoke(state, config=_config(state))

    assert len(result["deduped_evidence"]) == 1
    evidence = result["deduped_evidence"][0]
    assert evidence["content"] == "Telework is allowed two days a week."
    assert evidence["metadata"]["screenshot_url"] == "https://example.com/shots/doc-1-3.png"
    assert evidence["source_id"] == "doc-1"


def test_current_activity_is_updated_at_every_node_not_just_a_generic_placeholder(
    make_run,
):
    """Regression: nodes used to only post to the run_events log (fake.events) and never called
    update_run_status, so Run.current_node/current_activity - the only two fields a client
    polling GET /api/runs/{id} actually sees change - stayed empty for the whole run. The chat
    UI's placeholder ("Recherche en cours…") then never updated, looking like nothing happened.
    """

    def router(system_prompt: str) -> str:
        # complexity="complex" - a simple single-fact lookup skips validate_grounding entirely
        # (§ optimize latency), and this test wants every node exercised at least once.
        if "Analyze the user" in system_prompt:
            return _analysis(complexity="complex")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "The policy is X [abc]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the leave policy?")
    graph.invoke(state, config=_config(state))

    nodes_reported = {node for node, _activity in fake.activities}
    assert {
        "load_context",
        "load_accessible_vdbs",
        "analyze_query",
        "build_research_plan",
        "research_task",
        "merge_evidence",
        "evaluate_coverage",
        "build_answer_context",
        "generate_answer",
        "validate_grounding",
    } <= nodes_reported
    # Every activity string is distinct content, not the same generic placeholder repeated.
    assert len({activity for _node, activity in fake.activities}) > 1


def test_cancellation_before_search_stops_the_run_cleanly(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        return "unused"

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    fake.cancel_requested = True

    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert result["execution_status"] == "cancelled"
    assert result["answer"] is None


def test_qa_cache_hit_skips_chunk_search(make_run):
    """Tier 1 of the retrieval cascade (§ QA -> summaries -> chunks): a close-enough match in the
    QA cache answers the task directly, no vector search over chunks needed at all."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "Leave is 25 days a year [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.qa_hits = [
        {
            "qa_pair_id": "qa-1",
            "collection_id": "hr",
            "question": "How much leave?",
            "answer": "25 days a year.",
            "score": 0.93,
        }
    ]

    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == []
    assert len(result["deduped_evidence"]) == 1
    assert result["deduped_evidence"][0]["content"] == "25 days a year."


def test_a_cited_qa_pair_carries_the_source_it_comes_from(make_run):
    """What lets the chat open the source of a cited question-answer pair on its page (#351): the citation
    keeps the pair's answer as its content, and the document, page and passage apart."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "Leave is 25 days a year [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    source = {
        "document_id": "doc-1",
        "document_name": "handbook.pdf",
        "page_number": 4,
        "passage": "Employees get 25 days of leave.",
        "start": 120,
        "end": 151,
    }
    fake.qa_hits = [
        {
            "qa_pair_id": "qa-1",
            "collection_id": "hr",
            "question": "How much leave?",
            "answer": "25 days a year.",
            "score": 0.93,
            "source": source,
        },
    ]

    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    (citation,) = result["citations"]
    assert citation["evidence_kind"] == "qa" and citation["content"] == "25 days a year."
    assert citation["qa_source"] == source
    # Still no document to link a source row to: a QA citation is not a document citation.
    assert citation["document_id"] is None


def test_qa_cache_miss_falls_through_to_chunk_search(make_run):
    """A QA hit below the match threshold is not close enough - falls through exactly like no
    hit at all."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "The policy is X [abc]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.qa_hits = [
        {
            "qa_pair_id": "qa-1",
            "collection_id": "hr",
            "question": "unrelated",
            "answer": "unrelated",
            "score": 0.4,
        }
    ]

    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == [["hr"]]
    assert result["answer"] == "The policy is X [abc]."


def test_document_summaries_suffice_skips_chunk_search(make_run):
    """Tier 2: no QA hit, but the documents' own summaries already answer the question - still
    no chunk search needed."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "alone (without reading" in system_prompt:
            return json.dumps({"sufficient": True, "answer": "Telework is allowed two days a week."})
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "Telework is allowed two days a week [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.summary_hits = [
        {
            "document_id": "doc-1",
            "collection_id": "hr",
            "name": "handbook.pdf",
            "summary": "Covers telework and leave policy.",
            "score": 0.7,
        }
    ]

    state = initial_state("What is the telework policy?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == []
    assert len(result["deduped_evidence"]) == 1
    assert result["deduped_evidence"][0]["content"] == "Telework is allowed two days a week."


def test_partial_summary_is_flagged_to_the_judge(make_run):
    """A summary written from some pages of a long document is flagged as such, with the pages it covers (#372)."""
    seen: list[str] = []

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "alone (without reading" in system_prompt:
            seen.append(system_prompt)
            return json.dumps({"sufficient": False, "answer": None})
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "ok [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.summary_hits = [
        {
            "document_id": "doc-1",
            "collection_id": "hr",
            "name": "handbook.pdf",
            "summary": "Covers telework.",
            "summary_pages": [[1, 30], [71, 100]],
            "score": 0.7,
        }
    ]

    state = initial_state("What does article 12 say?")
    graph.invoke(state, config=_config(state))

    assert "partial" in seen[0] and "never enough" in seen[0]


def test_summary_line_flags_only_partial_summaries():
    from app.graph.nodes.research_task import _summary_line

    assert _summary_line({"name": "a.pdf", "summary": "S"}) == "a.pdf: S"
    assert _summary_line({"name": "a.pdf", "summary": "S", "summary_pages": [[1, 30], [100, 100]]}) == (
        "a.pdf [partial summary: pages 1-30, 100 only]: S"
    )


def test_no_qa_hit_no_summary_falls_through_to_chunk_search(make_run):
    """Neither tier 1 nor tier 2 has anything - falls through to the original chunk search,
    unchanged from before this cascade existed."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "alone (without reading" in system_prompt:
            return json.dumps({"sufficient": False, "answer": None})
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        return "The policy is X [abc]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.summary_hits = [
        {
            "document_id": "doc-1",
            "collection_id": "hr",
            "name": "handbook.pdf",
            "summary": "An unrelated summary.",
            "score": 0.3,
        }
    ]

    state = initial_state("What is the leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == [["hr"]]
    assert result["answer"] == "The policy is X [abc]."


def test_time_tool_provides_current_time_and_periods(make_run):
    """The time tool gives the LLM the current date/time (second-precise) and pre-computed
    relative periods so it can answer temporal queries like 'documents added this week'.
    """

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "what is the current date and time",
                        "tool": "time",
                    }
                ]
            )
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Today is the current date [t1]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What is the current date and time?")
    result = graph.invoke(state, config=_config(state))

    assert len(result["deduped_evidence"]) == 1
    evidence = result["deduped_evidence"][0]
    assert evidence["metadata"]["evidence_kind"] == "time"
    assert evidence["metadata"]["tool"] == "time"
    # The content must include the current time (second-precise ISO 8601)
    assert "Current time:" in evidence["content"]
    assert "Relative periods" in evidence["content"]
    # Must include common periods
    assert "today:" in evidence["content"]
    assert "this_week:" in evidence["content"]
    assert "last_week:" in evidence["content"]
    assert "this_month:" in evidence["content"]
    assert "last_month:" in evidence["content"]
    assert "last_7_days:" in evidence["content"]
    assert "last_30_days:" in evidence["content"]
    # No backend search should have been called
    assert fake.searched_collection_ids == []


def test_time_tool_is_offered_by_the_planner(make_run):
    """The decompose_query prompt must list 'time' as an available tool so the planner
    can pick it for temporal queries."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            # Verify the planner prompt mentions the time tool
            assert '"time"' in system_prompt
            return json.dumps([{"id": "t1", "query": "current time", "tool": "time"}])
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "The current time is now [t1]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What time is it?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["t1"]
    assert any(e["metadata"]["tool"] == "time" for e in result["deduped_evidence"])


def test_time_tool_evidence_has_second_precision(make_run):
    """The time tool must provide second-level precision (not just date or minute)."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps([{"id": "t1", "query": "current time", "tool": "time"}])
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Now [t1]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What is the current time?")
    result = graph.invoke(state, config=_config(state))

    evidence = result["deduped_evidence"][0]
    now_iso = evidence["metadata"]["now"]
    # ISO 8601 with seconds: YYYY-MM-DDTHH:MM:SS+HHMM
    import re

    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$"
    assert re.match(pattern, now_iso), f"Expected second-precision ISO, got {now_iso}"
    # The time field must include seconds
    assert len(evidence["metadata"]["time"]) == 8  # HH:MM:SS
    assert evidence["metadata"]["time"].count(":") == 2


# ─── tabular_query tool ──────────────────────────────────────────────────────


def _tabular_doc(collection_id: str = "hr", doc_id: str = "tab-1", name: str = "sales_data.csv", sheets=True) -> dict:
    """A tabular document as the backend's list_tabular_documents endpoint gives it (#433)."""
    return {
        "id": doc_id,
        "name": name,
        "format": "csv",
        "row_count": 1000,
        "column_count": 2,
        "columns": [],
        "measures": [],
        "dimensions": [],
        "text_columns": [],
        "sheets": (
            [
                {
                    "index": 0,
                    "name": "sales_data",
                    "rows": 1000,
                    "truncated": False,
                    "parquet_key": f"documents/{collection_id}/{doc_id}/tables/0.parquet",
                    "columns": [{"name": "category", "sql_type": "VARCHAR"}, {"name": "amount", "sql_type": "DOUBLE"}],
                    "profile": [{"name": "category", "distinct": 5, "top_values": ["books", "electronics"]}],
                }
            ]
            if sheets
            else []
        ),
    }


_LOOP_PROMPT = "Tu réponds à une question sur des données tabulaires"


def _tabular_router(steps: list[str], answer: str = "The total is 5000 [t1]."):
    """The router of a run whose tabular_query task has the model say `steps`, one reply per turn of its loop."""
    replies = iter(steps)

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps([{"id": "t1", "query": "total amount by category", "tool": "tabular_query"}])
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if _LOOP_PROMPT in system_prompt:
            return next(replies, '{"action": "finish"}')
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return answer

    return router


def _query(sql: str, files: list[str] | None = None) -> str:
    return json.dumps({"action": "query_data", "sql": sql, **({"files": files} if files else {})})


def _worker_result(columns: list[str], rows: list[list]) -> dict:
    return {
        "status": "completed",
        "columns": [{"name": name, "type": "VARCHAR"} for name in columns],
        "rows": rows,
        "truncated": False,
        "duration_ms": 3,
    }


def _worker_failure(message: str) -> dict:
    tables = [{"table": '"f1"."sales_data"', "columns": [{"name": "category", "type": "VARCHAR"}]}]
    return {"status": "failed", "message": message, "tables": tables, "duration_ms": 1}


def _fake_worker(monkeypatch, *answers: dict | Exception) -> list[dict]:
    """The SQL worker: answers each request in turn, and keeps the requests it was sent."""
    sent: list[dict] = []
    replies = iter(answers)

    def run(payload, *args, **kwargs):
        sent.append(payload)
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr("app.graph.services.tabular_query.run_remote_query", run)
    return sent


def test_tabular_query_tool_is_offered_by_the_planner(make_run):
    """The decompose_query prompt must list 'tabular_query' as an available tool so the planner
    can pick it for analytical questions on tabular data."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            # Verify the planner prompt mentions the tabular_query tool
            assert '"tabular_query"' in system_prompt
            return json.dumps(
                [
                    {
                        "id": "t1",
                        "query": "total amount by category",
                        "tool": "tabular_query",
                    }
                ]
            )
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "The total is 5000 [t1]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["t1"]


def test_tabular_query_tool_queries_the_sheets_through_the_sql_worker(make_run, monkeypatch):
    """The model writes SQL over the catalog, the SQL worker runs it, and the evidence carries SQL and result."""
    sql = 'SELECT category, SUM(amount) AS total FROM f1."sales_data" GROUP BY category'
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([_query(sql), '{"action": "finish"}']))
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc()]
    sent = _fake_worker(monkeypatch, _worker_result(["category", "total"], [["electronics", 3500], ["books", 1500]]))

    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["t1"]
    [evidence] = result["deduped_evidence"]
    assert evidence["metadata"]["evidence_kind"] == "tabular"
    assert evidence["metadata"]["document_name"] == "sales_data.csv"
    assert sql in evidence["content"]
    assert "| electronics | 3500 |" in evidence["content"] and "| books | 1500 |" in evidence["content"]
    assert evidence["source_id"] == "tab-1" and evidence["vdb_id"] == "hr"
    # The request holds what the backend listed - the key of the typed copy - and the collection it comes from.
    [request] = sent
    assert request["sql"] == sql and request["collection_ids"] == ["hr"]
    assert request["files"] == [
        {
            "ref": "f1",
            "sheets": [
                {
                    "name": "sales_data",
                    "key": "documents/hr/tab-1/tables/0.parquet",
                    "columns": [{"name": "category", "sql_type": "VARCHAR"}, {"name": "amount", "sql_type": "DOUBLE"}],
                }
            ],
        }
    ]


def test_tabular_query_tool_gives_the_model_the_catalog_and_the_worker_errors(make_run, monkeypatch):
    """A SQL in error comes back to the model with the message and the tables it can name; it corrects it, and the
    evidence keeps both calls."""
    bad = 'SELECT categ FROM f1."sales_data"'
    good = 'SELECT category FROM f1."sales_data"'
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([_query(bad), _query(good)]))
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc()]
    _fake_worker(
        monkeypatch,
        _worker_failure('Referenced column "categ" not found'),
        _worker_result(["category"], [["books"]]),
    )

    state = initial_state("What are the categories?")
    result = graph.invoke(state, config=_config(state))

    loop_messages = next(m for m in fake.llm_calls if _LOOP_PROMPT in m[0]["content"])
    assert 'table "f1"."sales_data"' in loop_messages[1]["content"]  # the catalog, up front
    corrected = [m for m in fake.llm_calls if _LOOP_PROMPT in m[0]["content"]][-1]
    assert any('"categ" not found' in m["content"] and '"f1"."sales_data"' in m["content"] for m in corrected)
    [evidence] = result["deduped_evidence"]
    assert bad in evidence["content"] and good in evidence["content"]
    assert "Referenced column" in evidence["content"]
    assert [c["ok"] for c in evidence["metadata"]["calls"]] == [False, True]


def test_tabular_query_tool_joins_two_files_and_cites_both(make_run, monkeypatch):
    sql = 'SELECT 1 FROM f1."sales_data" a JOIN f2."sales_data" b ON a.category = b.category'
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([_query(sql, ["f1", "f2"])]))
    fake.tabular_documents_by_collection["hr"] = [
        _tabular_doc(doc_id="tab-1", name="a.csv"),
        _tabular_doc(doc_id="tab-2", name="b.csv"),
    ]
    sent = _fake_worker(monkeypatch, _worker_result(["n"], [[1]]))

    state = initial_state("Join them")
    result = graph.invoke(state, config=_config(state))

    assert [f["ref"] for f in sent[0]["files"]] == ["f1", "f2"]
    assert sorted(e["source_id"] for e in result["deduped_evidence"]) == ["tab-1", "tab-2"]
    assert {e["metadata"]["document_name"] for e in result["deduped_evidence"]} == {"a.csv", "b.csv"}


def test_tabular_query_produces_no_evidence_when_no_tabular_documents(make_run, monkeypatch):
    """No tabular document in the selected collection: no evidence, the run still completes."""
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([]))
    sent = _fake_worker(monkeypatch)

    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["t1"]
    assert result["deduped_evidence"] == [] and sent == []


def test_a_document_without_a_typed_copy_is_announced_and_never_queried(make_run, monkeypatch):
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([]))
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc(name="old.csv", sheets=False)]
    sent = _fake_worker(monkeypatch)

    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert sent == []
    [evidence] = result["deduped_evidence"]
    assert "old.csv" in evidence["content"] and "réindexer" in evidence["content"]


def test_tabular_query_produces_no_evidence_when_the_model_gives_no_valid_action(make_run, monkeypatch):
    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router(["I think the total is 5", "still no JSON"]))
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc()]
    sent = _fake_worker(monkeypatch)

    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert result["completed_task_ids"] == ["t1"] and result["deduped_evidence"] == [] and sent == []


def test_a_sql_worker_that_does_not_answer_fails_the_task_with_a_clear_message(make_run, monkeypatch):
    from app.graph.services.tabular_worker import SqlWorkerUnavailable

    graph, fake = make_run(_hr_eng_vdbs(), _tabular_router([_query('SELECT 1 FROM f1."sales_data"')]))
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc()]
    _fake_worker(monkeypatch, SqlWorkerUnavailable("Le worker de requêtes n'a pas répondu en 120 secondes."))

    state = initial_state("What is the total amount by category?")
    result = graph.invoke(state, config=_config(state))

    assert result["failed_task_ids"] == ["t1"]
    failed = next(t for t in result["research_tasks"] if t["id"] == "t1")
    assert "n'a pas répondu" in failed["error"]


def test_analytical_query_does_not_short_circuit_to_search(make_run):
    """A simple-looking query that contains an analytical keyword (average, total, count, etc.)
    must NOT short-circuit to a plain 'search' task. It must go through the LLM planner so it can
    pick 'tabular_query' when appropriate. Without this, 'quel est le revenu moyen ?' would be
    classified as simple/lookup and forced to 'search', missing tabular data entirely.
    """

    planner_called = False

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()  # simple/lookup - would short-circuit without the analytical guard
        if "Break the user" in system_prompt:
            nonlocal planner_called
            planner_called = True
            return json.dumps([{"id": "t1", "query": "average revenue", "tool": "tabular_query"}])
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "The average is 15308.89 [t1]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.tabular_documents_by_collection["hr"] = [_tabular_doc()]

    state = initial_state("Quel est le revenu fiscal de reference moyen ?")
    result = graph.invoke(state, config=_config(state))

    # The planner must have been called (not short-circuited to search)
    assert planner_called, "analytical query must go through the LLM planner, not short-circuit to search"
    assert result["completed_task_ids"] == ["t1"]


def test_identity_query_short_circuits_to_answer_identity(make_run):
    """ "Qui es-tu ?" must never reach decompose_query/search (§ issue #97's original complaint:
    it used to come back empty-handed) - analyze_query classifying it as "identity" routes
    straight to answer_identity instead."""
    decompose_called = False

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="identity")
        if "Break the user's query" in system_prompt:
            nonlocal decompose_called
            decompose_called = True
            return json.dumps([{"id": "t1", "query": "qui es-tu ?", "tool": "search"}])
        if "You are Muffin" in system_prompt:
            return "I'm Muffin, I can search your collections and answer with citations."
        return "unexpected prompt"

    graph, fake = make_run(_hr_eng_vdbs(), router)
    state = initial_state("Qui es-tu ?")
    result = graph.invoke(state, config=_config(state))

    assert not decompose_called, "an identity question must never reach the research planner"
    assert fake.searched_collection_ids == []
    assert result["research_tasks"] == []
    assert result["answer"] == "I'm Muffin, I can search your collections and answer with citations."
    assert result["citations"] == []
    # No evidence to fact-check, no grounding pass either.
    assert result["grounding_result"] is None


def test_insufficient_coverage_suggests_web_search_when_not_enabled(make_run):
    """§ issue #95 - when the run never opted into web search and coverage stays insufficient
    when nobody can be asked, generate_answer must be told to suggest enabling it."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "insufficient", "missing_information": ["2025 update"], "reasoning": "x"})
        if "Answer the user's query" in system_prompt:
            return "I couldn't find that, but you could enable web search."
        return "unexpected prompt"

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the 2025 leave policy?", web_search_enabled=False, interactive=False)
    graph.invoke(state, config=_config(state))

    answer_call = next(call for call in fake.llm_calls if "Answer the user's query" in call[0]["content"])
    assert "enabling web search" in answer_call[1]["content"]


def test_insufficient_coverage_does_not_repeat_web_search_suggestion_when_already_enabled(make_run):
    """§ issue #95 - if web search was already on for this run and still came up short, there's
    nothing left to suggest enabling."""

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps([{"query": "2025 policy update", "intent": None}])
        if "Answer the user's query" in system_prompt:
            return "I still couldn't find that."
        return "unexpected prompt"

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the 2025 leave policy?", web_search_enabled=True, interactive=False)
    graph.invoke(state, config=_config(state))

    answer_call = next(call for call in fake.llm_calls if "Answer the user's query" in call[0]["content"])
    assert "enabling web search" not in answer_call[1]["content"]


# --- Flat routing over sub-collections (#233) ---


def _hr_tree() -> list[dict]:
    """HR > Leave > Parental leave, plus a flat Engineering root."""
    return [
        {"id": "hr", "parent_id": None, "name": "HR", "description": "HR policies", "tags": []},
        {"id": "leave", "parent_id": "hr", "name": "Leave", "description": "Leave policies", "tags": []},
        {"id": "parental", "parent_id": "leave", "name": "Parental", "description": "Parental leave", "tags": []},
        {"id": "eng", "parent_id": None, "name": "Engineering", "description": "Eng docs", "tags": []},
    ]


def _routing_router(picks: list[str]):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return json.dumps(picks)
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "Parental leave is 16 weeks [abc]."

    return router


def _answer_prompt(fake) -> str:
    return next(call for call in fake.llm_calls if "Answer the user's query" in call[0]["content"])[1]["content"]


def test_search_reaches_a_deep_sub_collection_and_reports_what_the_cap_left_out(make_run, monkeypatch):
    from app.graph.services import vdb_router

    monkeypatch.setattr(vdb_router.settings, "MAX_ROUTED_COLLECTIONS", 1)
    graph, fake = make_run(_hr_tree(), _routing_router(["hr", "parental"]))
    state = initial_state("What is the parental leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == [["hr"]]
    assert result["unexplored_vdb_ids"] == ["hr"]  # parental was picked but over the cap
    assert "go further" in _answer_prompt(fake)


def test_go_further_routes_over_the_sub_collections_of_the_frontier(make_run):
    graph, fake = make_run(_hr_tree(), _routing_router([]))
    state = initial_state("What is the parental leave policy?", resume_from_vdb_ids=["leave"])
    result = graph.invoke(state, config=_config(state))

    assert fake.searched_collection_ids == [["parental"]]
    assert result["unexplored_vdb_ids"] == []
    assert "go further" not in _answer_prompt(fake)


def test_citations_carry_the_path_of_their_collection(make_run):
    graph, _ = make_run(_hr_tree(), _routing_router(["hr", "parental"]))
    state = initial_state("What is the parental leave policy?")
    result = graph.invoke(state, config=_config(state))

    paths = {citation["vdb_id"]: citation["vdb_path"] for citation in result["citations"]}
    assert paths["parental"] == ["HR", "Leave", "Parental"]
    assert paths["hr"] == ["HR"]


def test_the_run_starts_from_the_frontier_pinning_already_left_unexplored(make_run):
    graph, fake = make_run(_hr_tree(), _routing_router(["hr"]))
    state = initial_state("What is the parental leave policy?")
    state["unexplored_vdb_ids"] = ["leave"]
    result = graph.invoke(state, config=_config(state))

    assert "leave" in result["unexplored_vdb_ids"]
    assert "HR › Leave" in _answer_prompt(fake)


def _answer_router(system_prompt: str) -> str:
    if "Analyze the user" in system_prompt:
        return _analysis()
    if "select the ones relevant" in system_prompt.lower():
        return '["hr"]'
    if "Decide whether" in system_prompt:
        return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
    if "Check whether every" in system_prompt:
        return json.dumps({"valid": True, "unsupported_claims": []})
    return "Leave is 25 days [x]."


def test_answer_is_published_while_it_is_being_written(make_run):
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _answer_router)
    state = initial_state("How many days of leave?")
    result = graph.invoke(state, config=_config(state))

    # Cleared first, then the text written so far (the last piece may fall within the publishing interval).
    assert fake.partial_answers[0] == ""
    assert result["answer"] == "Leave is 25 days [x]."
    assert result["answer_prompt_tokens"] == 100
    assert result["answer_completion_tokens"] == 50


def test_answer_falls_back_to_one_piece_when_streaming_fails(make_run):
    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], _answer_router)
    fake.stream_error = RuntimeError("stream unavailable")
    state = initial_state("How many days of leave?")
    result = graph.invoke(state, config=_config(state))

    assert result["answer"] == "Leave is 25 days [x]."
