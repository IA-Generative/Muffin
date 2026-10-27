from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.graph.nodes.analyze_query import analyze_query
from app.graph.nodes.answer_help import answer_help
from app.graph.nodes.answer_identity import answer_identity
from app.graph.nodes.build_answer_context import build_answer_context
from app.graph.nodes.build_research_plan import build_research_plan
from app.graph.nodes.clarify_coverage import clarify_coverage
from app.graph.nodes.create_document import delegate_create, detect_create
from app.graph.nodes.decompose_query import decompose_query
from app.graph.nodes.delegate_edit import delegate_edit
from app.graph.nodes.detect_edit import detect_edit
from app.graph.nodes.evaluate_coverage import evaluate_coverage
from app.graph.nodes.generate_answer import generate_answer
from app.graph.nodes.load_accessible_vdbs import load_accessible_vdbs
from app.graph.nodes.load_context import load_context
from app.graph.nodes.merge_evidence import merge_evidence
from app.graph.nodes.request_clarification import request_clarification
from app.graph.nodes.research_task import research_task
from app.graph.nodes.route_collections import route_collections
from app.graph.nodes.targeted_research import targeted_research
from app.graph.nodes.validate_grounding import validate_grounding
from app.graph.routing.conditions import (
    after_analyze_query,
    after_clarify_coverage,
    after_detect_create,
    after_detect_edit,
    after_evaluate_coverage,
    after_generate_answer,
    after_request_clarification,
    after_route_collections,
    after_validate_grounding,
    continue_dag_or_evaluate,
    route_or_cancel,
)
from app.graph.services.node_metrics import measured
from app.graph.state import AgentState, ResearchTaskInput


def _cancellable_edge(graph: StateGraph, source: str, target: str) -> None:
    graph.add_conditional_edges(source, route_or_cancel(target), {target: target, "cancelled": "cancelled"})


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(AgentState)

    graph.add_node("load_context", measured("load_context", load_context))
    graph.add_node("load_accessible_vdbs", measured("load_accessible_vdbs", load_accessible_vdbs))
    graph.add_node("detect_edit", measured("detect_edit", detect_edit))
    graph.add_node("detect_create", measured("detect_create", detect_create))
    graph.add_node("delegate_create", measured("delegate_create", delegate_create))
    graph.add_node("delegate_edit", measured("delegate_edit", delegate_edit))
    graph.add_node("analyze_query", measured("analyze_query", analyze_query))
    graph.add_node("answer_identity", measured("answer_identity", answer_identity))
    graph.add_node("answer_help", measured("answer_help", answer_help))
    graph.add_node("request_clarification", measured("request_clarification", request_clarification))
    graph.add_node("decompose_query", measured("decompose_query", decompose_query))
    graph.add_node("build_research_plan", measured("build_research_plan", build_research_plan))
    graph.add_node("route_collections", measured("route_collections", route_collections))
    # `research_task` runs with the narrower ResearchTaskInput schema (§11) - each fan-out branch
    # only sees its own task, never the others (input_schema pins that at the graph level too).
    graph.add_node("research_task", measured("research_task", research_task), input_schema=ResearchTaskInput)
    graph.add_node("merge_evidence", measured("merge_evidence", merge_evidence))
    graph.add_node("evaluate_coverage", measured("evaluate_coverage", evaluate_coverage))
    graph.add_node("clarify_coverage", measured("clarify_coverage", clarify_coverage))
    graph.add_node("build_answer_context", measured("build_answer_context", build_answer_context))
    graph.add_node("generate_answer", measured("generate_answer", generate_answer))
    graph.add_node("validate_grounding", measured("validate_grounding", validate_grounding))
    graph.add_node("targeted_research", measured("targeted_research", targeted_research))
    # Cancellation (§30) is a fan-in target: any routing function may send the run here instead
    # of its normal next node, and every path converges on the same clean exit.
    graph.add_node("cancelled", lambda _state: {"execution_status": "cancelled"})

    graph.set_entry_point("load_context")
    _cancellable_edge(graph, "load_context", "load_accessible_vdbs")
    _cancellable_edge(graph, "load_accessible_vdbs", "detect_edit")
    # A request to change a living document (#171) is handed to the editing agent instead of being
    # searched for as if it were a question; anything else carries on to analyze_query as before.
    graph.add_conditional_edges(
        "detect_edit",
        after_detect_edit,
        {"delegate_edit": "delegate_edit", "detect_create": "detect_create", "cancelled": "cancelled"},
    )
    _cancellable_edge(graph, "delegate_edit", END)
    # A request to write a new document is answered with a proposal to validate, not searched for.
    graph.add_conditional_edges(
        "detect_create",
        after_detect_create,
        {"delegate_create": "delegate_create", "analyze_query": "analyze_query", "cancelled": "cancelled"},
    )
    _cancellable_edge(graph, "delegate_create", END)
    graph.add_conditional_edges(
        "analyze_query",
        after_analyze_query,
        {
            "request_clarification": "request_clarification",
            "decompose_query": "decompose_query",
            "answer_identity": "answer_identity",
            "answer_help": "answer_help",
            "cancelled": "cancelled",
        },
    )
    # Asking ends the run (the answer comes with the next message); not asking carries on with assumptions.
    graph.add_conditional_edges(
        "request_clarification",
        after_request_clarification,
        {"decompose_query": "decompose_query", "end": END, "cancelled": "cancelled"},
    )
    # Terminal like generate_answer/validate_grounding, just without the grounding pass -
    # nothing here to fact-check against evidence, there's no evidence at all.
    _cancellable_edge(graph, "answer_identity", END)
    _cancellable_edge(graph, "answer_help", END)
    _cancellable_edge(graph, "decompose_query", "build_research_plan")
    # Dynamic fan-out (§9/§10): however many tasks are ready becomes that many Send()s to
    # research_task, capped by the parallelism/total-task budgets (§28).
    _cancellable_edge(graph, "build_research_plan", "route_collections")
    # Nothing dominating where to search ends the run on a question; otherwise the fan-out goes ahead.
    graph.add_conditional_edges(
        "route_collections",
        after_route_collections,
        {"research_task": "research_task", "merge_evidence": "merge_evidence", "cancelled": "cancelled", "end": END},
    )
    graph.add_edge("research_task", "merge_evidence")
    # A task blocked on a dependency becomes ready only once that dependency shows up in
    # completed_task_ids (§27) - re-entering the fan-out gate here (instead of going straight to
    # evaluate_coverage) is what actually drains the DAG; also reused by the grounding loop
    # (targeted_research -> merge_evidence) since build_answer_context/generate_answer always
    # need a coverage pass first regardless of which loop produced the new evidence.
    graph.add_conditional_edges(
        "merge_evidence", continue_dag_or_evaluate, ["research_task", "evaluate_coverage", "cancelled"]
    )
    graph.add_conditional_edges(
        "evaluate_coverage",
        after_evaluate_coverage,
        {
            "build_answer_context": "build_answer_context",
            "clarify_coverage": "clarify_coverage",
            "cancelled": "cancelled",
        },
    )
    # Insufficient coverage ends the run on questions to the user rather than looping on more research:
    # the answer comes with their next message.
    graph.add_conditional_edges("clarify_coverage", after_clarify_coverage, {"end": END, "cancelled": "cancelled"})
    _cancellable_edge(graph, "build_answer_context", "generate_answer")
    # Grounding is skipped for a deterministic knowledge-base lookup or a simple single-fact
    # answer (§ optimize latency) - see after_generate_answer for exactly which.
    graph.add_conditional_edges(
        "generate_answer",
        after_generate_answer,
        {"end": END, "validate_grounding": "validate_grounding", "cancelled": "cancelled"},
    )
    # Grounding loop (§23/§24): a failed check triggers one narrow round of targeted research,
    # then re-generates and re-validates, bounded by MAX_GROUNDING_RESEARCHES.
    graph.add_conditional_edges(
        "validate_grounding",
        after_validate_grounding,
        {"end": END, "targeted_research": "targeted_research", "cancelled": "cancelled"},
    )
    _cancellable_edge(graph, "targeted_research", "merge_evidence")
    graph.add_edge("cancelled", END)

    # Defaults to an in-process InMemorySaver, which is only safe for tests and single-process
    # runs - it cannot survive a HITL pause being resumed by a different Celery prefork child
    # than the one that ran interrupt() (§32). Production wires a real cross-process checkpointer
    # in via this parameter (see agent_service.py) rather than hardcoding one here.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
