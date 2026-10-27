import json

from tests.test_graph import _analysis, _config, initial_state


def _vdbs() -> list[dict]:
    return [
        {"id": "hr", "name": "HR", "description": "People policies", "tags": []},
        {"id": "fin", "name": "Finance", "description": "Budgets", "tags": []},
        {"id": "eng", "name": "Engineering", "description": "Specs", "tags": []},
    ]


def _router(system_prompt: str) -> str:
    if "Analyze the user" in system_prompt:
        return _analysis()
    if "select the ones relevant" in system_prompt.lower():
        return '["hr"]'
    if "Decide whether" in system_prompt:
        return json.dumps({"status": "sufficient", "missing_information": [], "reasoning": "ok"})
    if "Check whether every" in system_prompt:
        return json.dumps({"valid": True, "unsupported_claims": []})
    return "answer [x]."


def _hits(**ranks: float) -> list[dict]:
    return [{"collection_id": collection_id, "rank": rank} for collection_id, rank in ranks.items()]


def _decisions(fake) -> list[str]:
    return [data["decision"] for type_, data in fake.event_data if type_ == "routing_confidence"]


def test_a_flat_probe_ends_the_run_on_a_question_proposing_the_closest_collections(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.5, fin=0.45, eng=0.4)
    state = initial_state("What is the policy?")

    result = graph.invoke(state, config=_config(state))

    assert _decisions(fake) == ["flat"]
    assert fake.searched_collection_ids == []  # nothing was searched: asked first
    question = result["questions"][0]
    assert question["multi_select"] is True
    assert [option["label"] for option in question["options"]] == ["HR", "Finance", "Engineering"]
    assert question["options"][0]["description"] == "People policies"
    assert result["citations"] == []
    assert [d for t, d in fake.event_data if t == "clarification_requested"][0]["questions"] == result["questions"]


def test_a_clear_probe_searches_without_asking(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.9, fin=0.1)
    state = initial_state("What is the leave policy?")

    result = graph.invoke(state, config=_config(state))

    assert _decisions(fake) == ["clear"]
    assert not result.get("questions")
    assert fake.searched_collection_ids


def test_a_leaning_probe_searches_without_asking(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.5, fin=0.3, eng=0.2)
    state = initial_state("What is the leave policy?")

    result = graph.invoke(state, config=_config(state))

    assert _decisions(fake) == ["lean"]
    assert not result.get("questions")


def test_collections_attached_by_the_user_are_never_probed(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.5, fin=0.45, eng=0.4)
    state = {**initial_state("What is the policy?"), "pinned_vdb_ids": ["fin"]}

    result = graph.invoke(state, config=_config(state))

    assert fake.probed_collection_ids == []
    assert not result.get("questions")


def test_the_message_after_a_question_is_never_asked_again(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.5, fin=0.45, eng=0.4)
    state = {**initial_state("HR or finance, both"), "question_rounds": 1}

    result = graph.invoke(state, config=_config(state))

    assert _decisions(fake) == ["flat"]  # still measured
    assert not result.get("questions")
    assert fake.searched_collection_ids


def test_a_run_nobody_reads_is_never_asked(make_run):
    graph, fake = make_run(_vdbs(), _router)
    fake.probe_hits = _hits(hr=0.5, fin=0.45, eng=0.4)
    state = {**initial_state("What is the policy?"), "interactive": False}

    result = graph.invoke(state, config=_config(state))

    assert not result.get("questions")
    assert fake.searched_collection_ids


def test_a_probe_that_finds_nothing_leaves_routing_as_it_was(make_run):
    graph, fake = make_run(_vdbs(), _router)
    state = initial_state("What is the policy?")

    result = graph.invoke(state, config=_config(state))

    assert _decisions(fake) == ["unknown"]
    assert not result.get("questions")
    assert fake.searched_collection_ids


def test_a_single_accessible_collection_is_not_probed(make_run):
    graph, fake = make_run(_vdbs()[:1], _router)
    state = initial_state("What is the policy?")

    graph.invoke(state, config=_config(state))

    assert fake.probed_collection_ids == []
