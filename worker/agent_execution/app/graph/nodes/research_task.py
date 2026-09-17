from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.events import emit, is_cancelled
from app.graph.services.evidence import normalize_results
from app.graph.services.llm import default_model
from app.graph.services.vdb_router import select_relevant_vdbs
from app.graph.state import ResearchTaskInput


def research_task(state: ResearchTaskInput) -> dict[str, Any]:
    """Central research node (§11) - one call handles exactly one ResearchTask and knows nothing
    about the others. It orchestrates VDB routing + search as plain service calls (§35: these are
    not themselves LangGraph nodes, only research_task is)."""
    run_id, task = state["run_id"], state["task"]
    task_id = task["id"]

    if is_cancelled(run_id):
        return {"research_tasks": [{**task, "status": "failed", "error": "cancelled"}], "failed_task_ids": [task_id]}

    emit(run_id, "task_started", {"query": task["query"]}, task_id=task_id)
    try:
        emit(run_id, "vdb_routing_started", task_id=task_id)
        selected_vdbs = select_relevant_vdbs(task["query"], state["accessible_vdbs"], default_model())
        emit(run_id, "vdb_routing_completed", {"selected_ids": [str(v["id"]) for v in selected_vdbs]}, task_id=task_id)

        if not selected_vdbs:
            completed = {**task, "status": "completed", "selected_vdbs": [], "results": []}
            emit(run_id, "task_completed", {"evidence_count": 0}, task_id=task_id)
            return {"research_tasks": [completed], "completed_task_ids": [task_id]}

        emit(run_id, "search_started", {"vdb_count": len(selected_vdbs)}, task_id=task_id)
        results = backend_client.search(
            [str(v["id"]) for v in selected_vdbs], task["query"], settings.SEARCH_RESULTS_PER_QUERY
        )
        emit(run_id, "search_completed", {"result_count": len(results)}, task_id=task_id)

        evidence = normalize_results(task_id, task["query"], results)
        emit(run_id, "evidence_updated", {"evidence_count": len(evidence)}, task_id=task_id)

        completed = {
            **task,
            "status": "completed",
            "selected_vdbs": [str(v["id"]) for v in selected_vdbs],
            "search_queries": [task["query"]],
            "results": results,
        }
        emit(run_id, "task_completed", {"evidence_count": len(evidence)}, task_id=task_id)
        return {"research_tasks": [completed], "completed_task_ids": [task_id], "evidence": evidence}
    except Exception as error:
        # One branch failing must not take the whole run down (§29) - evaluate_coverage decides
        # afterwards whether the surviving tasks are enough to answer with.
        logger.exception(f"Research task {task_id} failed (run {run_id})")
        emit(run_id, "task_failed", {"error": str(error)}, task_id=task_id)
        return {"research_tasks": [{**task, "status": "failed", "error": str(error)}], "failed_task_ids": [task_id]}
