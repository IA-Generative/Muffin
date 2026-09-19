import uuid
from typing import Any

from loguru import logger

from app.backend_client import backend_client
from app.config import settings
from app.graph.services.document_resolver import resolve_document_page
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.evidence import normalize_results
from app.graph.services.llm import json_chat
from app.graph.services.vdb_router import select_relevant_vdbs
from app.graph.state import Evidence, ResearchTaskInput
from app.searxng_client import searxng_client

# Ranking score (Meilisearch hybrid search, §12: blended lexical + cosine-vector) above which a
# previously answered question counts as "this one, already answered" rather than merely related -
# conservative on purpose, a false match here means citing a wrong answer, not just a missed
# shortcut.
_QA_MATCH_THRESHOLD = 0.85

_SUMMARY_SUFFICIENCY_PROMPT = (
    "Given a query and the summaries of the documents in a knowledge base, decide whether these summaries "
    "alone (without reading the documents' full content) are enough to answer it completely and precisely. "
    'Respond only with JSON: {"sufficient": bool, "answer": string or null - a complete, precise answer '
    "using only the given summaries, set only when sufficient is true}."
)


def _collection_evidence(vdb: dict[str, Any], task_id: str, retrieval_query: str) -> Evidence:
    content = (
        f"Knowledge base collection '{vdb['name']}': {vdb['description']} ({vdb.get('document_count', 0)} document(s))"
    )
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=str(vdb["id"]),
        # No document_id to cite - this is a collection-level meta-fact, not a document page.
        source_id="",
        content=content,
        # "document_name" is what build_answer_context reads as a citation's display label
        # (§15) - reused here for a collection's own name so the sources panel shows "AgentControl"
        # rather than a bare vdb id.
        metadata={
            "document_name": vdb["name"],
            "document_count": vdb.get("document_count", 0),
        },
        relevance_score=None,
        retrieval_query=retrieval_query,
    )


def _count_fact_evidence(
    task_id: str,
    retrieval_query: str,
    noun: str,
    count: int,
    vdb_id: str = "",
    label: str | None = None,
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
        # No document_id to cite - this is a count fact, not a document page.
        source_id="",
        content=content,
        metadata={
            "document_name": label or "Accessible knowledge bases",
            "count": count,
        },
        relevance_score=None,
        retrieval_query=retrieval_query,
    )


def _qa_evidence(task_id: str, retrieval_query: str, hit: dict[str, Any]) -> Evidence:
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=str(hit["collection_id"]),
        # No document_id to cite - a QA hit is a previously answered question, not a document
        # page. source_id=None prevents build_answer_context from passing collection_id as
        # document_id to link_citations (which would FK-violate on sources.document_id).
        source_id="",
        content=hit["answer"],
        metadata={
            "document_name": "Question déjà répondue",
            "qa_pair_id": str(hit["qa_pair_id"]),
        },
        relevance_score=hit["score"],
        retrieval_query=retrieval_query,
    )


def _summary_evidence(task_id: str, retrieval_query: str, vdb: dict[str, Any], answer: str) -> Evidence:
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=str(vdb["id"]),
        # Same as _qa_evidence: a summary-derived answer has no specific document_id to cite.
        source_id="",
        content=answer,
        metadata={"document_name": vdb["name"]},
        relevance_score=None,
        retrieval_query=retrieval_query,
    )


def _web_result_evidence(task_id: str, retrieval_query: str, result: dict[str, Any]) -> Evidence:
    # vdb_id="": this evidence never came from a Muffin collection - build_answer_context/the
    # frontend's sources panel key off metadata["tool"]=="web_search" (stamped centrally by
    # research_task below), not vdb_id, to tell a web result apart from a knowledge-base one.
    title = result.get("title") or result["url"]
    snippet = result.get("content") or ""
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id="",
        source_id=result["url"],
        content=f"{title}\n\n{snippet}" if snippet else title,
        metadata={
            "document_name": title,
            "url": result["url"],
            "engine": result.get("engine", ""),
        },
        relevance_score=result.get("score"),
        retrieval_query=retrieval_query,
    )


_SUMMARY_MATCH_LIMIT = 5


def _summaries_suffice(query: str, summaries: list[dict[str, Any]], model: str | None) -> tuple[bool, str | None]:
    """Tier 2 of the research agent's retrieval cascade (§ QA -> summaries -> chunks): before
    ever running a full chunk search, ask whether the top-matching documents' own summaries
    already answer the query - cheaper and often already precise enough for "what is X
    about"-style questions. Only the top _SUMMARY_MATCH_LIMIT summaries (found by vector search
    over summary embeddings, see backend_client.search_summaries), never every document in the
    collection - that wouldn't scale to a collection with hundreds of them."""
    if model is None:
        return False, None
    listing = "\n\n".join(f"{s['name']}: {s['summary']}" for s in summaries if s.get("summary"))
    if not listing:
        return False, None
    raw = json_chat(
        model,
        _SUMMARY_SUFFICIENCY_PROMPT,
        f"Query: {query}\n\nDocument summaries:\n{listing}",
        fallback={"sufficient": False, "answer": None},
    )
    if not isinstance(raw, dict):
        return False, None
    return bool(raw.get("sufficient")), raw.get("answer")


def _run_search(
    task: dict[str, Any],
    _user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    pinned_vdb_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict[str, Any], list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, model, pinned_vdb_ids)
    if not selected_vdbs:
        return {"selected_vdbs": [], "results": []}, []
    vdb_ids = [str(v["id"]) for v in selected_vdbs]
    vdb_names = {str(v["id"]): v["name"] for v in selected_vdbs}
    base_updates = {"selected_vdbs": vdb_ids, "search_queries": [task["query"]]}

    # Tier 1: has this exact question already been answered (a QA pair), in these collections?
    qa_hits = backend_client.search_qa(vdb_ids, task["query"], limit=1)
    if qa_hits and qa_hits[0]["score"] >= _QA_MATCH_THRESHOLD:
        evidence = [_qa_evidence(task["id"], task["query"], qa_hits[0])]
        return {**base_updates, "results": []}, evidence

    # Tier 2: do the best-matching documents' own summaries already answer it, without reading
    # full chunks?
    summary_hits = backend_client.search_summaries(vdb_ids, task["query"], limit=_SUMMARY_MATCH_LIMIT)
    sufficient, summary_answer = _summaries_suffice(task["query"], summary_hits, model)
    if sufficient and summary_answer:
        top_vdb_id = str(summary_hits[0]["collection_id"]) if summary_hits else vdb_ids[0]
        vdb = {"id": top_vdb_id, "name": vdb_names.get(top_vdb_id, top_vdb_id)}
        evidence = [_summary_evidence(task["id"], task["query"], vdb, summary_answer)]
        return {**base_updates, "results": []}, evidence

    # Tier 3: the original, unconditional behavior - full vector search over the chunks.
    results = backend_client.search(vdb_ids, task["query"], settings.SEARCH_RESULTS_PER_QUERY)
    evidence = normalize_results(task["id"], task["query"], results)
    return {**base_updates, "results": results}, evidence


def _run_list_collections(task: dict[str, Any], accessible_vdbs: list[dict[str, Any]]) -> tuple[dict, list[Evidence]]:
    # No backend call and no VDB routing at all here - the user is asking about the accessible
    # set itself (§4), which load_accessible_vdbs already fetched for this exact permission
    # reason, not narrowed by relevance since every accessible collection is the answer.
    evidence = [_collection_evidence(vdb, task["id"], task["query"]) for vdb in accessible_vdbs]
    evidence.append(_count_fact_evidence(task["id"], task["query"], "knowledge base collection", len(accessible_vdbs)))
    return {"selected_vdbs": [str(v["id"]) for v in accessible_vdbs]}, evidence


def _run_collection_summary(
    task: dict[str, Any],
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    pinned_vdb_ids: list[str],
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, model, pinned_vdb_ids)
    evidence = [_collection_evidence(vdb, task["id"], task["query"]) for vdb in selected_vdbs]
    return {"selected_vdbs": [str(v["id"]) for v in selected_vdbs]}, evidence


def _run_list_documents(
    task: dict[str, Any],
    user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    pinned_vdb_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, model, pinned_vdb_ids)
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
                    metadata={
                        "document_name": document["name"],
                        "status": document["status"],
                    },
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
    task: dict[str, Any],
    user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    pinned_vdb_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = select_relevant_vdbs(task["query"], accessible_vdbs, model, pinned_vdb_ids)
    if not selected_vdbs:
        return {"selected_vdbs": []}, []

    # Only one page is ever fetched per task - resolve against the first matching collection's
    # documents, same permission-scoped candidate list list_documents itself uses.
    vdb = selected_vdbs[0]
    candidates = backend_client.list_collection_documents(user_id, str(vdb["id"]))
    document_id, page_number = resolve_document_page(task["query"], candidates, model)
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


def _run_web_search(
    task: dict[str, Any],
    _user_id: str,
    _accessible_vdbs: list[dict[str, Any]],
    _model: str | None,
    _pinned_vdb_ids: list[str],
    web_search_enabled: bool,
) -> tuple[dict[str, Any], list[Evidence]]:
    if not web_search_enabled:
        # Second, independent gate (see decompose_query._sanitize) against a stale/malformed
        # task claiming this tool on a run that never opted in - must never call out to the
        # web on the strength of the planner's own output alone.
        logger.warning(f"Task {task['id']} requested web_search on a run with web_search_enabled=False - refused")
        return {"results": []}, []

    # The query sent out is always this task's own query - decomposed from the user's original
    # question by decompose_query, never document excerpts/evidence content (§ security: this
    # is what keeps private document content from ever leaking into a web search request).
    results = searxng_client.search(task["query"], settings.WEB_SEARCH_RESULTS_PER_QUERY)
    evidence = [_web_result_evidence(task["id"], task["query"], result) for result in results]
    return {"results": [{"url": r["url"]} for r in results]}, evidence


_RUNNERS = {
    "list_collections": lambda task, user_id, accessible_vdbs, model, pinned_vdb_ids, web_search_enabled: (
        _run_list_collections(task, accessible_vdbs)
    ),
    "collection_summary": lambda task, user_id, accessible_vdbs, model, pinned_vdb_ids, web_search_enabled: (
        _run_collection_summary(task, accessible_vdbs, model, pinned_vdb_ids)
    ),
    "list_documents": _run_list_documents,
    "page_content": _run_page_content,
    "web_search": _run_web_search,
}


def research_task(state: ResearchTaskInput) -> dict[str, Any]:
    """Central research node (§11) - one call handles exactly one ResearchTask and knows nothing
    about the others. It orchestrates VDB routing + search/meta-lookups as plain service calls
    (§35: these are not themselves LangGraph nodes, only research_task is). `task["tool"]` picks
    which of those services actually runs - content search by default, or a knowledge-base
    introspection lookup (collection/document counts and summaries, page content) chosen by
    decompose_query. Every lookup still goes through the same accessible_vdbs permission
    barrier (§4/§12): a tool never reaches a collection or document this user can't access.
    """
    run_id, task, user_id = state["run_id"], state["task"], state["user_id"]
    task_id = task["id"]

    if is_cancelled(run_id):
        return {
            "research_tasks": [{**task, "status": "failed", "error": "cancelled"}],
            "failed_task_ids": [task_id],
        }

    set_activity(run_id, "research_task", task["query"])
    emit(
        run_id,
        "task_started",
        {"query": task["query"], "tool": task["tool"]},
        task_id=task_id,
    )
    try:
        emit(run_id, "vdb_routing_started", task_id=task_id)
        runner = _RUNNERS.get(task["tool"], _run_search)
        updates, evidence = runner(
            task,
            user_id,
            state["accessible_vdbs"],
            state["chat_model"],
            state["pinned_vdb_ids"],
            state["web_search_enabled"],
        )
        # Stamped centrally here (not in each runner) so every evidence-producing branch tags
        # itself the same way, once - lets a citation say which tool produced it (§ sources
        # panel: a "search" citation links to a real page/chunk, a meta-tool one is just
        # input/output, no page to link to).
        evidence = [{**e, "metadata": {**e["metadata"], "tool": task["tool"]}} for e in evidence]
        emit(
            run_id,
            "vdb_routing_completed",
            {"selected_ids": updates.get("selected_vdbs", [])},
            task_id=task_id,
        )

        completed = {**task, "status": "completed", **updates}
        emit(run_id, "task_completed", {"evidence_count": len(evidence)}, task_id=task_id)
        return {
            "research_tasks": [completed],
            "completed_task_ids": [task_id],
            "evidence": evidence,
        }
    except Exception as error:
        # One branch failing must not take the whole run down (§29) - evaluate_coverage decides
        # afterwards whether the surviving tasks are enough to answer with.
        logger.exception(f"Research task {task_id} failed (run {run_id})")
        emit(run_id, "task_failed", {"error": str(error)}, task_id=task_id)
        return {
            "research_tasks": [{**task, "status": "failed", "error": str(error)}],
            "failed_task_ids": [task_id],
        }
