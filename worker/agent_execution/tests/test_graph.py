import json

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
        {"id": "hr", "name": "HR", "description": "HR policies", "tags": []},
        {"id": "eng", "name": "Engineering", "description": "Engineering docs", "tags": []},
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
    assert result["grounding_result"]["valid"] is True


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
    assert {e["task_id"] for e in result["deduped_evidence"]} == {"telework", "leave", "benefits"}


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


def test_insufficient_coverage_triggers_a_targeted_replan(make_run):
    calls = {"coverage": 0}

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            calls["coverage"] += 1
            if calls["coverage"] == 1:
                return json.dumps(
                    {"status": "insufficient", "missing_information": ["2025 update"], "reasoning": "stale"}
                )
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Coverage of a research query" in system_prompt:
            return json.dumps([{"query": "2025 policy update", "intent": None}])
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the current leave policy?")
    result = graph.invoke(state, config=_config(state))

    assert result["replan_count"] == 1
    assert result["plan_version"] == 1
    assert any(task_id.startswith("replan-1-") for task_id in result["completed_task_ids"])


def test_grounding_failure_triggers_targeted_research(make_run):
    calls = {"grounding": 0}

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis()
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


def test_ambiguous_query_interrupts_for_clarification_then_resumes(make_run):
    from langgraph.types import Command

    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(ambiguous=True, clarification_question="Which department do you mean?")
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "answer [x]."

    graph, fake = make_run([{"id": "hr", "name": "HR", "description": "HR", "tags": []}], router)
    state = initial_state("What is the policy?")
    config = _config(state)

    paused = graph.invoke(state, config=config)
    assert "__interrupt__" in paused
    assert paused["__interrupt__"][0].value["question"] == "Which department do you mean?"

    resumed = graph.invoke(Command(resume="HR department"), config=config)
    assert "__interrupt__" not in resumed
    assert resumed["answer"] == "answer [x]."


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
