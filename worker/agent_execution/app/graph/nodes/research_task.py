import uuid
from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.document_resolver import resolve_document_page
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.evidence import normalize_results
from app.graph.services.llm import default_model
from app.graph.services.vdb_router import select_relevant_vdbs
from app.graph.state import Evidence, ResearchTaskInput


def _collection_evidence(vdb: dict[str, Any], task_id: str, retrieval_query: str) -> Evidence:
    content = (
        f"Knowledge base collection '{vdb['name']}': {vdb['description']} ({vdb.get('document_count', 0)} document(s))"
    )
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=str(vdb["id"]),
        source_id=str(vdb["id"]),
        content=content,
        # "document_name" is what build_answer_context reads as a citation's display label
        # (§15) - reused here for a collection's own name so the sources panel shows "AgentControl"
        # rather than a bare vdb id.
        metadata={"document_name": vdb["name"], "document_count": vdb.get("document_count", 0)},
        relevance_score=None,
        retrieval_query=retrieval_query,
    )


def _count_fact_evidence(
    task_id: str, retrieval_query: str, noun: str, count: int, vdb_id: str = "", label: str | None = None
) -> Evidence:
    # A literal, unambiguous sentence rather than relying on generate_answer's LLM to count
    # excerpts itself - tested against a real local model, it sometimes refused to (treating a
    # description as unrelated to "your collections" instead of counting the items it was given).
    plural = "" if count == 1 else "s"
    content = f"You have exactly {count} accessible {noun}{plural}."
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=vdb_id,
        source_id=vdb_id,
        content=content,
        metadata={"document_name": label or "Accessible knowledge bases", "count": count},
        relevance_score=None,
        retrieval_query=retrieval_query,
    )


def _run_search(task: dict[str, Any], accessible_vdbs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, default_model())
    if not selected_vdbs:
        return {"selected_vdbs": [], "results": []}, []

    results = backend_client.search(
        [str(v["id"]) for v in selected_vdbs], task["query"], settings.SEARCH_RESULTS_PER_QUERY
    )
    evidence = normalize_results(task["id"], task["query"], results)
    updates = {
        "selected_vdbs": [str(v["id"]) for v in selected_vdbs],
        "search_queries": [task["query"]],
        "results": results,
    }
    return updates, evidence


def _run_list_collections(task: dict[str, Any], accessible_vdbs: list[dict[str, Any]]) -> tuple[dict, list[Evidence]]:
    # No backend call and no VDB routing at all here - the user is asking about the accessible
    # set itself (§4), which load_accessible_vdbs already fetched for this exact permission
    # reason, not narrowed by relevance since every accessible collection is the answer.
    evidence = [_collection_evidence(vdb, task["id"], task["query"]) for vdb in accessible_vdbs]
    evidence.append(_count_fact_evidence(task["id"], task["query"], "knowledge base collection", len(accessible_vdbs)))
    return {"selected_vdbs": [str(v["id"]) for v in accessible_vdbs]}, evidence


def _run_collection_summary(task: dict[str, Any], accessible_vdbs: list[dict[str, Any]]) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, default_model())
    evidence = [_collection_evidence(vdb, task["id"], task["query"]) for vdb in selected_vdbs]
    return {"selected_vdbs": [str(v["id"]) for v in selected_vdbs]}, evidence


def _run_list_documents(
    task: dict[str, Any], user_id: str, accessible_vdbs: list[dict[str, Any]]
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, default_model())
    evidence: list[Evidence] = []
    for vdb in selected_vdbs:
        documents = backend_client.list_collection_documents(user_id, str(vdb["id"]))
        for document in documents:
            content = f"{document['name']} ({document['status']}): {document['summary'] or 'no summary yet'}"
            evidence.append(
                Evidence(
                    id=str(uuid.uuid4()),
                    task_id=task["id"],
                    vdb_id=str(vdb["id"]),
                    source_id=str(document["id"]),
                    content=content,
                    metadata={"document_name": document["name"], "status": document["status"]},
                    relevance_score=None,
                    retrieval_query=task["query"],
                )
            )
        count = len(documents)
        evidence.append(
            Evidence(
                id=str(uuid.uuid4()),
                task_id=task["id"],
                vdb_id=str(vdb["id"]),
                source_id=str(vdb["id"]),
                content=f"The '{vdb['name']}' collection has exactly {count} document{'' if count == 1 else 's'}.",
                metadata={"document_name": vdb["name"], "count": count},
                relevance_score=None,
                retrieval_query=task["query"],
            )
        )
    return {"selected_vdbs": [str(v["id"]) for v in selected_vdbs]}, evidence


def _run_page_content(
    task: dict[str, Any], user_id: str, accessible_vdbs: list[dict[str, Any]]
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, default_model())
    if not selected_vdbs:
        return {"selected_vdbs": []}, []

    # Only one page is ever fetched per task - resolve against the first matching collection's
    # documents, same permission-scoped candidate list list_documents itself uses.
    vdb = selected_vdbs[0]
    candidates = backend_client.list_collection_documents(user_id, str(vdb["id"]))
    document_id, page_number = resolve_document_page(task["query"], candidates, default_model())
    if document_id is None or page_number is None:
        return {"selected_vdbs": [str(vdb["id"])]}, []

    page = backend_client.get_document_page(user_id, document_id, page_number)
    document_name = next((c["name"] for c in candidates if str(c["id"]) == document_id), document_id)
    evidence = [
        Evidence(
            id=str(uuid.uuid4()),
            task_id=task["id"],
            vdb_id=str(vdb["id"]),
            source_id=document_id,
            content=page["content"],
            metadata={
                "document_name": document_name,
                "page_number": page["page_number"],
                "screenshot_url": page.get("screenshot_url"),
            },
            relevance_score=None,
            retrieval_query=task["query"],
        )
    ]
    return {"selected_vdbs": [str(vdb["id"])]}, evidence


_RUNNERS = {
    "list_collections": lambda task, user_id, accessible_vdbs: _run_list_collections(task, accessible_vdbs),
    "collection_summary": lambda task, user_id, accessible_vdbs: _run_collection_summary(task, accessible_vdbs),
    "list_documents": _run_list_documents,
    "page_content": _run_page_content,
}


def research_task(state: ResearchTaskInput) -> dict[str, Any]:
    """Central research node (§11) - one call handles exactly one ResearchTask and knows nothing
    about the others. It orchestrates VDB routing + search/meta-lookups as plain service calls
    (§35: these are not themselves LangGraph nodes, only research_task is). `task["tool"]` picks
    which of those services actually runs - content search by default, or a knowledge-base
    introspection lookup (collection/document counts and summaries, page content) chosen by
    decompose_query. Every lookup still goes through the same accessible_vdbs permission
    barrier (§4/§12): a tool never reaches a collection or document this user can't access."""
    run_id, task, user_id = state["run_id"], state["task"], state["user_id"]
    task_id = task["id"]

    if is_cancelled(run_id):
        return {"research_tasks": [{**task, "status": "failed", "error": "cancelled"}], "failed_task_ids": [task_id]}

    set_activity(run_id, "research_task", task["query"])
    emit(run_id, "task_started", {"query": task["query"], "tool": task["tool"]}, task_id=task_id)
    try:
        emit(run_id, "vdb_routing_started", task_id=task_id)
        runner = _RUNNERS.get(task["tool"], lambda t, u, v: _run_search(t, v))
        updates, evidence = runner(task, user_id, state["accessible_vdbs"])
        emit(run_id, "vdb_routing_completed", {"selected_ids": updates.get("selected_vdbs", [])}, task_id=task_id)

        completed = {**task, "status": "completed", **updates}
        emit(run_id, "task_completed", {"evidence_count": len(evidence)}, task_id=task_id)
        return {"research_tasks": [completed], "completed_task_ids": [task_id], "evidence": evidence}
    except Exception as error:
        # One branch failing must not take the whole run down (§29) - evaluate_coverage decides
        # afterwards whether the surviving tasks are enough to answer with.
        logger.exception(f"Research task {task_id} failed (run {run_id})")
        emit(run_id, "task_failed", {"error": str(error)}, task_id=task_id)
        return {"research_tasks": [{**task, "status": "failed", "error": str(error)}], "failed_task_ids": [task_id]}
