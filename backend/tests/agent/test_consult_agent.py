"""An A2A agent consulted by the plan (#a2a): unlike `call_tool`, the query itself is the message sent, and what
comes back is the agent's own answer - evidence of its own kind, attributed to that agent."""

from app.agent.graph.nodes import research_task as research_module
from app.agent.graph.nodes.research_task import _run_consult_agent


class Backend:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def call_tool(self, run_id, ref, arguments):
        self.calls.append((run_id, ref, arguments))
        return self.result


TASK = {
    "id": "task-1",
    "query": "quel est le solde de congés de l'agent ?",
    "tool": "consult_agent",
    "agent_ref": "tool-1",
    "agent_name": "RH Bot",
}


async def run(monkeypatch, result):
    backend = Backend(result)
    monkeypatch.setattr(research_module, "backend_client", backend)
    updates, evidence = await _run_consult_agent(TASK, "u", [], "m", [], False, run_id="run-1")
    return backend, updates, evidence


async def test_the_agents_answer_is_evidence_of_its_own_kind(monkeypatch):
    backend, _, evidence = await run(monkeypatch, {"ok": True, "code": "ok", "text": "12 jours restants"})

    # The message sent is the task's own query, verbatim - never arguments to fill in a schema.
    assert backend.calls == [("run-1", "tool-1", {"message": "quel est le solde de congés de l'agent ?"})]
    assert len(evidence) == 1 and "12 jours restants" in evidence[0]["content"]
    assert evidence[0]["metadata"]["evidence_kind"] == "agent"
    assert evidence[0]["metadata"]["document_name"] == "Agent : RH Bot"
    assert evidence[0]["relevance_score"] == 1.0


async def test_a_truncated_answer_says_so(monkeypatch):
    _, _, evidence = await run(monkeypatch, {"ok": True, "code": "ok", "text": "x", "truncated": True})

    assert "[réponse tronquée]" in evidence[0]["content"]


async def test_an_agent_that_could_not_answer_is_said_to_the_answer_with_its_code(monkeypatch):
    _, _, evidence = await run(monkeypatch, {"ok": False, "code": "delai_depasse", "text": "Trop long"})

    assert "n'a pas pu répondre (delai_depasse)" in evidence[0]["content"]
    assert evidence[0]["metadata"]["tool_ok"] is False and evidence[0]["metadata"]["tool_code"] == "delai_depasse"


async def test_consulting_an_agent_asks_the_persons_agreement_first_and_nothing_is_sent_yet(monkeypatch):
    _, _, evidence = await run(
        monkeypatch,
        {
            "ok": False,
            "code": "confirmation_demandee",
            "text": "Cet outil modifie des données : ...",
            "arguments": {"message": "quel est le solde de congés de l'agent ?"},
        },
    )

    content = evidence[0]["content"]
    assert "RH Bot" in content and "RIEN N'A ÉTÉ DEMANDÉ À L'AGENT" in content
    assert "quel est le solde de congés de l'agent ?" in content
    assert evidence[0]["metadata"]["tool_ok"] is False
    assert evidence[0]["metadata"]["tool_code"] == "confirmation_demandee"


# --- through the whole graph ---

from tests.agent.conftest import initial_state  # noqa: E402
from tests.agent.test_graph import VDBS, _config, router  # noqa: E402

AGENT_TOOL = {
    "ref": "tool-1",
    "name": "demander",
    "description": "Demande à l'agent « RH Bot »",
    "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
    "server_id": "s1",
    "server_name": "RH Bot",
    "protocol": "a2a",
    "side_effect": False,
}


async def test_the_plan_consults_an_agent_the_backend_asks_and_the_answer_gets_its_result(make_run):
    plan = {
        "mode": "search",
        "queries": [{"query": "quel est le solde de congés ?", "tool": "consult_agent", "ref": "tool-1"}],
    }
    graph, fake = make_run(VDBS, router(plan))
    fake.tools = [AGENT_TOOL]
    fake.tool_result = {"ok": True, "code": "ok", "text": "12 jours restants"}
    state = initial_state("Quel est mon solde de congés ?")

    result = await graph.ainvoke(state, config=_config(state))

    assert fake.tool_calls == [("tool-1", {"message": "quel est le solde de congés ?"})]
    assert fake.searched_collection_ids == []  # asked the agent, not the documents
    assert "ref=tool-1" in fake.llm_calls[0][0]["content"]  # the plan was told what it may consult
    assert any(e["metadata"].get("evidence_kind") == "agent" for e in result["deduped_evidence"])


async def test_an_agent_is_never_reachable_through_call_tool(make_run):
    plan = {
        "mode": "search",
        "queries": [
            {"query": "q", "tool": "call_tool", "ref": "tool-1", "arguments": {"message": "q"}},
        ],
    }
    graph, fake = make_run(VDBS, router(plan))
    fake.tools = [AGENT_TOOL]
    state = initial_state("Quel est mon solde de congés ?")

    await graph.ainvoke(state, config=_config(state))

    # Named through the wrong tool: the call is refused and it falls back to a plain search.
    assert getattr(fake, "tool_calls", []) == [] and fake.searched_collection_ids != []


async def test_an_assistant_that_turns_agent_consultation_off_cannot_consult_an_agent(make_run):
    plan = {
        "mode": "search",
        "queries": [{"query": "q", "tool": "consult_agent", "ref": "tool-1"}],
    }
    graph, fake = make_run(VDBS, router(plan))
    fake.tools = [AGENT_TOOL]
    state = initial_state("Quel est mon solde de congés ?")
    state["disabled_tools"] = ["consult_agent"]

    result = await graph.ainvoke(state, config=_config(state))

    # What the plan picked is checked against the tools that are on, not only the guide (#343's own rule, reused):
    # a disabled consult_agent falls back to a plain search, whatever the model asked for.
    assert getattr(fake, "tool_calls", []) == []
    assert not any(e["metadata"].get("evidence_kind") == "agent" for e in result["deduped_evidence"])
