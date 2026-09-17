from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from app.graph.nodes.analyze_query import analyze_query
from app.graph.nodes.build_answer_context import build_answer_context
from app.graph.nodes.build_research_plan import build_research_plan
from app.graph.nodes.decompose_query import decompose_query
from app.graph.nodes.evaluate_coverage import evaluate_coverage
from app.graph.nodes.generate_answer import generate_answer
from app.graph.nodes.load_accessible_vdbs import load_accessible_vdbs
from app.graph.nodes.load_context import load_context
from app.graph.nodes.merge_evidence import merge_evidence
from app.graph.nodes.replan_research import replan_research
from app.graph.nodes.request_clarification import request_clarification
from app.graph.nodes.research_task import research_task
from app.graph.nodes.targeted_research import targeted_research
from app.graph.nodes.validate_grounding import validate_grounding
from app.graph.routing.conditions import (
    after_analyze_query,
    after_evaluate_coverage,
    after_validate_grounding,
    continue_dag_or_evaluate,
    execute_research_plan,
    route_or_cancel,
)
from app.graph.state import AgentState, ResearchTaskInput


def _cancellable_edge(graph: StateGraph, source: str, target: str) -> None:
    graph.add_conditional_edges(source, route_or_cancel(target), {target: target, "cancelled": "cancelled"})


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("load_context", load_context)
    graph.add_node("load_accessible_vdbs", load_accessible_vdbs)
    graph.add_node("analyze_query", analyze_query)
    graph.add_node("request_clarification", request_clarification)
    graph.add_node("decompose_query", decompose_query)
    graph.add_node("build_research_plan", build_research_plan)
    # `research_task` runs with the narrower ResearchTaskInput schema (§11) - each fan-out branch
    # only sees its own task, never the others (input_schema pins that at the graph level too).
    graph.add_node("research_task", research_task, input_schema=ResearchTaskInput)
    graph.add_node("merge_evidence", merge_evidence)
    graph.add_node("evaluate_coverage", evaluate_coverage)
    graph.add_node("replan_research", replan_research)
    graph.add_node("build_answer_context", build_answer_context)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("validate_grounding", validate_grounding)
    graph.add_node("targeted_research", targeted_research)
    # Cancellation (§30) is a fan-in target: any routing function may send the run here instead
    # of its normal next node, and every path converges on the same clean exit.
    graph.add_node("cancelled", lambda _state: {"execution_status": "cancelled"})

    graph.set_entry_point("load_context")
    _cancellable_edge(graph, "load_context", "load_accessible_vdbs")
    _cancellable_edge(graph, "load_accessible_vdbs", "analyze_query")
    graph.add_conditional_edges(
        "analyze_query",
        after_analyze_query,
        {
            "request_clarification": "request_clarification",
            "decompose_query": "decompose_query",
            "cancelled": "cancelled",
        },
    )
    _cancellable_edge(graph, "request_clarification", "decompose_query")
    _cancellable_edge(graph, "decompose_query", "build_research_plan")
    # Dynamic fan-out (§9/§10): however many tasks are ready becomes that many Send()s to
    # research_task, capped by the parallelism/total-task budgets (§28).
    fan_out_targets = ["research_task", "merge_evidence", "cancelled"]
    graph.add_conditional_edges("build_research_plan", execute_research_plan, fan_out_targets)
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
            "replan_research": "replan_research",
            "cancelled": "cancelled",
        },
    )
    # Replan loop (§19/§20): a targeted replan re-enters the same fan-out gate rather than a
    # separate execution path, bounded by MAX_REPLANS in after_evaluate_coverage.
    graph.add_conditional_edges("replan_research", execute_research_plan, fan_out_targets)
    _cancellable_edge(graph, "build_answer_context", "generate_answer")
    _cancellable_edge(graph, "generate_answer", "validate_grounding")
    # Grounding loop (§23/§24): a failed check triggers one narrow round of targeted research,
    # then re-generates and re-validates, bounded by MAX_GROUNDING_RESEARCHES.
    graph.add_conditional_edges(
        "validate_grounding",
        after_validate_grounding,
        {"end": END, "targeted_research": "targeted_research", "cancelled": "cancelled"},
    )
    _cancellable_edge(graph, "targeted_research", "merge_evidence")
    graph.add_edge("cancelled", END)

    # In-memory checkpointer for now (§32) - swapping in a Postgres-backed one is an infra
    # change (out of scope here per the brief), but every node already reads/writes through
    # AgentState so that swap is just this one line once that backend is wired up.
    return graph.compile(checkpointer=InMemorySaver())
