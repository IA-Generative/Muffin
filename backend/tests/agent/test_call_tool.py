"""A tool called by the plan (#343): the run takes the result as evidence, says when the tool could not be used, and the
tools are asked of the backend once, and only for a run that can choose among them."""

from app.agent.graph.nodes import research_task as research_module
from app.agent.graph.nodes.research_task import _run_call_tool


class Backend:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def call_tool(self, run_id, ref, arguments):
        self.calls.append((run_id, ref, arguments))
        return self.result


TASK = {
    "id": "task-1",
    "query": "combien font 2+2 ?",
    "tool": "call_tool",
    "tool_ref": "internal.calculatrice",
    "arguments": {"expression": "2+2"},
}


async def run(monkeypatch, result):
    backend = Backend(result)
    monkeypatch.setattr(research_module, "backend_client", backend)
    updates, evidence = await _run_call_tool(TASK, "u", [], "m", [], False, run_id="run-1")
    return backend, updates, evidence


async def test_the_result_of_a_tool_is_evidence_that_reaches_the_answer(monkeypatch):
    backend, _, evidence = await run(
        monkeypatch, {"ok": True, "code": "ok", "text": "2+2 = 4", "tool_name": "calculatrice"}
    )

    assert backend.calls == [("run-1", "internal.calculatrice", {"expression": "2+2"})]
    assert len(evidence) == 1 and "2+2 = 4" in evidence[0]["content"] and "calculatrice" in evidence[0]["content"]
    assert evidence[0]["metadata"]["evidence_kind"] == "tool" and evidence[0]["relevance_score"] == 1.0


async def test_the_server_a_result_comes_from_is_named_and_a_cut_result_says_so(monkeypatch):
    _, _, evidence = await run(
        monkeypatch,
        {
            "ok": True,
            "code": "ok",
            "text": "dossier 12",
            "tool_name": "chercher",
            "server_name": "Dossiers",
            "truncated": True,
        },
    )

    assert "serveur Dossiers" in evidence[0]["content"] and "[résultat tronqué]" in evidence[0]["content"]


async def test_a_tool_that_could_not_be_used_is_said_to_the_answer_with_its_code(monkeypatch):
    _, _, evidence = await run(
        monkeypatch, {"ok": False, "code": "quota_depasse", "text": "Trop d'appels", "tool_name": "calculatrice"}
    )

    assert "n'a pas pu être utilisé (quota_depasse)" in evidence[0]["content"]
    assert evidence[0]["metadata"]["tool_ok"] is False and evidence[0]["metadata"]["tool_code"] == "quota_depasse"


# --- through the whole graph ---

from tests.agent.conftest import initial_state  # noqa: E402
from tests.agent.test_graph import VDBS, _config, router  # noqa: E402

CALCULATOR = {
    "ref": "internal.calculatrice",
    "name": "calculatrice",
    "description": "Calcule",
    "input_schema": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
}


async def test_the_plan_calls_a_tool_the_backend_runs_and_the_answer_gets_its_result(make_run):
    plan = {
        "mode": "search",
        "queries": [
            {"query": "2+2 ?", "tool": "call_tool", "ref": "internal.calculatrice", "arguments": {"expression": "2+2"}}
        ],
    }
    graph, fake = make_run(VDBS, router(plan))
    fake.tools = [CALCULATOR]
    state = initial_state("Combien font 2+2 ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert fake.tool_calls == [("internal.calculatrice", {"expression": "2+2"})]
    assert fake.searched_collection_ids == []  # asked the tool, not the documents
    assert "ref=internal.calculatrice" in fake.llm_calls[0][0]["content"]  # the plan was told what it may call
    assert any(e["metadata"].get("evidence_kind") == "tool" for e in result["deduped_evidence"])
    assert len(fake.llm_calls) == 2 and fake.tool_definitions_asked == 1  # plan and answer: the tool cost no model call


async def test_a_run_with_no_tools_is_what_it_was_and_the_plan_hears_of_none(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    state = initial_state("Combien ?")

    await graph.ainvoke(state, config=_config(state))

    assert fake.tool_definitions_asked == 1 and "call_tool" not in fake.llm_calls[0][0]["content"]


async def test_an_assistant_that_turns_the_tools_off_never_asks_for_them(make_run):
    graph, fake = make_run(VDBS, router({"mode": "search"}))
    fake.tools = [CALCULATOR]
    state = initial_state("Combien ?")
    state["disabled_tools"] = ["call_tool"]

    await graph.ainvoke(state, config=_config(state))

    assert (
        getattr(fake, "tool_definitions_asked", 0) == 0
        and "internal.calculatrice" not in fake.llm_calls[0][0]["content"]
    )
