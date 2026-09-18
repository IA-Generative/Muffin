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
        {"id": "hr", "name": "HR", "description": "HR policies", "tags": [], "document_count": 3},
        {"id": "eng", "name": "Engineering", "description": "Engineering docs", "tags": [], "document_count": 5},
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


def test_list_collections_tool_answers_from_accessible_vdbs_without_searching(make_run):
    def router(system_prompt: str) -> str:
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps([{"id": "t1", "query": "how many collections do I have", "tool": "list_collections"}])
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
    # sometimes refuse to, see test_meta_tool_never_replans_into_a_pointless_search's sibling bug).
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
            return json.dumps([{"id": "t1", "query": "how many collections do I have", "tool": "list_collections"}])
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
    hand. A meta-only task's evidence must be treated as complete without ever asking."""
    coverage_calls = 0

    def router(system_prompt: str) -> str:
        nonlocal coverage_calls
        if "Analyze the user" in system_prompt:
            return _analysis(intent="meta")
        if "Break the user's query" in system_prompt:
            return json.dumps(
                [{"id": "count-collections", "query": "how many collections", "tool": "list_collections"}]
            )
        if "Decide whether" in system_prompt:
            coverage_calls += 1
            # The real, observed failure mode: the LLM calls a legitimate meta answer
            # insufficient because the description doesn't literally state a count.
            return json.dumps(
                {"status": "insufficient", "missing_information": ["the number of collections"], "reasoning": "n/a"}
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
            return json.dumps([{"id": "t1", "query": "summarize the HR collection", "tool": "collection_summary"}])
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
            return json.dumps([{"id": "t1", "query": "how many documents in HR", "tool": "list_documents"}])
        if "select the ones relevant" in system_prompt.lower():
            return '["hr"]'
        if "Decide whether" in system_prompt:
            return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
        if "Check whether every" in system_prompt:
            return json.dumps({"valid": True, "unsupported_claims": []})
        return "There are 2 documents [x]."

    graph, fake = make_run(_hr_eng_vdbs(), router)
    fake.documents_by_collection["hr"] = [
        {"id": "doc-1", "name": "handbook.pdf", "status": "indexed", "summary": "Employee handbook."},
        {"id": "doc-2", "name": "leave-policy.pdf", "status": "indexed", "summary": "Leave policy."},
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
            return json.dumps([{"id": "t1", "query": "page 3 of the handbook", "tool": "page_content"}])
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
        {"id": "doc-1", "name": "handbook.pdf", "status": "indexed", "summary": "Employee handbook."},
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


def test_current_activity_is_updated_at_every_node_not_just_a_generic_placeholder(make_run):
    """Regression: nodes used to only post to the run_events log (fake.events) and never called
    update_run_status, so Run.current_node/current_activity - the only two fields a client
    polling GET /api/runs/{id} actually sees change - stayed empty for the whole run. The chat
    UI's placeholder ("Recherche en cours…") then never updated, looking like nothing happened."""

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
        {"qa_pair_id": "qa-1", "collection_id": "hr", "question": "unrelated", "answer": "unrelated", "score": 0.4}
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
