from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.graph.nodes.answer_help import answer_help
from app.agent.graph.nodes.build_answer_context import build_answer_context
from app.agent.graph.nodes.create import build_create_graph
from app.agent.graph.nodes.edit import build_edit_graph
from app.agent.graph.nodes.gate import gate, widen_search
from app.agent.graph.nodes.generate_answer import generate_answer
from app.agent.graph.nodes.guardrails import blocked, guardrails
from app.agent.graph.nodes.memory_command import memory_command
from app.agent.graph.nodes.merge_evidence import merge_evidence
from app.agent.graph.nodes.plan import plan
from app.agent.graph.nodes.prepare import prepare, prepare_request
from app.agent.graph.nodes.research_task import research_task
from app.agent.graph.routing.conditions import (
    after_gate,
    after_plan,
    after_prepare,
    after_widen_search,
    route_or_cancel,
)
from app.agent.graph.services.node_metrics import measured
from app.agent.graph.state import AgentState, ResearchTaskInput


def _cancellable_edge(graph: StateGraph, source: str, target: str) -> None:
    graph.add_conditional_edges(source, route_or_cancel(target), {target: target, "cancelled": "cancelled"})


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """The agent: one model call decides (`plan`), the research that follows is code, one model call writes the answer.

    (prepare || guardrails) -> prepare_request -> { blocked | plan -> { answer now | ask | help | edit | create |
        research -> gate -> (widen) -> answer } }

    The guardrails on the input (#516) run beside `prepare` and are waited for before the request is read by anything:
    a request they stop ends at `blocked`, with a refusal for an answer and no model reached.

    See docs/agent-execution-graph-proposal.md for the drawing and the budget of calls of each path."""
    graph = StateGraph(AgentState)

    graph.add_node("prepare", measured("prepare", prepare))
    graph.add_node("guardrails", measured("guardrails", guardrails))
    graph.add_node("prepare_request", measured("prepare_request", prepare_request))
    graph.add_node("blocked", measured("blocked", blocked))
    graph.add_node("plan", measured("plan", plan))
    graph.add_node("answer_help", measured("answer_help", answer_help))
    graph.add_node("memory_command", measured("memory_command", memory_command))
    # The edit and the creation of a document are sub-graphs: they share the run's state and never go back to research.
    graph.add_node("edit", build_edit_graph())
    graph.add_node("create", build_create_graph())
    # `research_task` runs with the narrower ResearchTaskInput schema (§11): a fan-out branch only sees its own task.
    graph.add_node("research_task", measured("research_task", research_task), input_schema=ResearchTaskInput)
    graph.add_node("merge_evidence", measured("merge_evidence", merge_evidence))
    graph.add_node("gate", measured("gate", gate))
    graph.add_node("widen_search", measured("widen_search", widen_search))
    graph.add_node("build_answer_context", measured("build_answer_context", build_answer_context))
    graph.add_node("generate_answer", measured("generate_answer", generate_answer))
    # Cancellation (§30) is a fan-in target: any routing function may send the run here instead of its normal next node.
    graph.add_node("cancelled", lambda _state: {"execution_status": "cancelled"})

    graph.add_edge(START, "prepare")
    graph.add_edge(START, "guardrails")
    # The join: `prepare_request` starts once both have ended, so what reads the request reads it as the guardrails
    # left it.
    graph.add_edge(["prepare", "guardrails"], "prepare_request")
    graph.add_conditional_edges(
        "prepare_request", after_prepare, {"plan": "plan", "blocked": "blocked", "cancelled": "cancelled"}
    )
    graph.add_edge("blocked", END)
    # The plan decides. Answering and asking end the run (the plan wrote the answer); a search fans out, one branch per
    # query, all at once.
    graph.add_conditional_edges(
        "plan",
        after_plan,
        {
            "answer_help": "answer_help",
            "memory_command": "memory_command",
            "edit": "edit",
            "create": "create",
            "research_task": "research_task",
            "gate": "gate",
            "cancelled": "cancelled",
            "end": END,
        },
    )
    for terminal in ("answer_help", "memory_command", "edit", "create"):
        _cancellable_edge(graph, terminal, END)
    graph.add_edge("research_task", "merge_evidence")
    _cancellable_edge(graph, "merge_evidence", "gate")
    graph.add_conditional_edges(
        "gate",
        after_gate,
        {"widen_search": "widen_search", "build_answer_context": "build_answer_context", "cancelled": "cancelled"},
    )
    graph.add_conditional_edges("widen_search", after_widen_search, ["research_task", "build_answer_context"])
    _cancellable_edge(graph, "build_answer_context", "generate_answer")
    # The answer ends the graph: the check of its claims (ground_check) is made after it is out, see AgentService.
    _cancellable_edge(graph, "generate_answer", END)
    graph.add_edge("cancelled", END)

    # Defaults to an in-process InMemorySaver, which is only safe for tests and single-process runs; production wires a
    # real cross-process checkpointer in via this parameter (see agent_service.py).
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
