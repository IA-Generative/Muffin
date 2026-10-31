import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from typing import Any

from loguru import logger

from app.agent.backend_client import backend_client
from app.agent.config import settings
from app.agent.graph.services.document_resolver import resolve_document_page
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.evidence import normalize_results
from app.agent.graph.services.scope import scope_vdbs
from app.agent.graph.services.tabular_catalog import Catalog
from app.agent.graph.services.tabular_query import LoopOutcome, format_tabular_evidence, run_query_loop
from app.agent.graph.services.time_tool import build_time_context, format_time_context
from app.agent.graph.state import Evidence, ResearchTaskInput
from app.agent.searxng_client import searxng_client

# Cosine between the question and a previously answered one (the score the backend returns is the cosine
# of the dense vectors, not the rank-based score of the BM25 + dense fusion that orders the hits, #355)
# above which that question counts as "this one, already answered" rather than merely related -
# conservative on purpose, a false match here means citing a wrong answer, not just a missed
# shortcut. A pair only the lexical branch found has a low cosine and never passes.
_QA_MATCH_THRESHOLD = 0.85
# The fusion orders the candidates, the cosine decides: the best of a few is looked at, not just the first.
_QA_CANDIDATES = 3


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
            "evidence_kind": "collection",
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
            "evidence_kind": "collection",
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
            "evidence_kind": "qa",
            # Where the answer comes from (#351): the document, page and passage the pair was generated from,
            # when it has them - what opens its source on that page with the passage framed. Kept apart from
            # `source_id`/`document_id`, which stay empty: a QA citation is not a document citation.
            "qa_source": hit.get("source"),
        },
        relevance_score=hit["score"],
        retrieval_query=retrieval_query,
    )


def _summary_evidence(task_id: str, retrieval_query: str, hit: dict[str, Any]) -> Evidence:
    """The summary of a document the question lands in: context about it as a whole, read with the passages. It cites
    the document by its name but has no page to open (the summary is of the whole document), so it is not a "document"
    evidence."""
    pages = hit.get("summary_pages")
    partial = f" [partial summary: pages {_pages_text(pages)} only]" if pages else ""
    return Evidence(
        id=str(uuid.uuid4()),
        task_id=task_id,
        vdb_id=str(hit["collection_id"]),
        source_id=str(hit["document_id"]),
        content=f"{hit['name']}{partial}: {hit['summary']}",
        metadata={"document_name": hit["name"], "evidence_kind": "summary"},
        relevance_score=hit.get("score"),
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
            "evidence_kind": "web",
        },
        relevance_score=result.get("score"),
        retrieval_query=retrieval_query,
    )


_SUMMARY_MATCH_LIMIT = 5


def _pages_text(ranges: list[list[int]]) -> str:
    return ", ".join(f"{start}-{end}" if start != end else str(start) for start, end in ranges)


def _best_effort(call: Any, default: Any) -> Any:
    """The QA and the summaries only add to what the chunks give: failing to read them never fails the search."""
    try:
        return call()
    except Exception:
        logger.exception("A search tier failed, going on without it")
        return default


def _run_search(
    task: dict[str, Any],
    _user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    _model: str | None,
    scope_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict[str, Any], list[Evidence]]:
    """The content search, with no model: one query to each of the three tiers - a question already answered (QA), the
    summaries of the documents, the chunks - in the chosen collections and the ones below them, all at once. A
    question already answered counts first when it is the same question; the summaries add the document as a whole."""
    selected_vdbs = scope_vdbs(scope_ids, accessible_vdbs)
    if not selected_vdbs:
        return {"selected_vdbs": [], "results": []}, []
    vdb_ids = [str(v["id"]) for v in selected_vdbs]
    base_updates = {"selected_vdbs": vdb_ids, "search_queries": [task["query"]], "unexplored_vdb_ids": []}
    query = task["query"]

    # Each call in a copy of the context of the run (who it is for, their token): a pool's threads do not inherit it.
    with ThreadPoolExecutor(max_workers=3) as pool:
        qa_future = pool.submit(
            copy_context().run,
            _best_effort,
            lambda: backend_client.search_qa(vdb_ids, query, limit=_QA_CANDIDATES, include_descendants=True),
            [],
        )
        summary_future = pool.submit(
            copy_context().run,
            _best_effort,
            lambda: backend_client.search_summaries(
                vdb_ids, query, limit=_SUMMARY_MATCH_LIMIT, include_descendants=True
            ),
            [],
        )
        chunk_future = pool.submit(
            copy_context().run,
            lambda: backend_client.search(vdb_ids, query, settings.SEARCH_RESULTS_PER_QUERY, include_descendants=True),
        )
        qa_hits, summary_hits, results = qa_future.result(), summary_future.result(), chunk_future.result()

    evidence: list[Evidence] = []
    if qa_hits and qa_hits[0]["score"] >= _QA_MATCH_THRESHOLD:
        evidence.append(_qa_evidence(task["id"], query, qa_hits[0]))
    evidence += [_summary_evidence(task["id"], query, hit) for hit in summary_hits if hit.get("summary")]
    evidence += normalize_results(task["id"], query, results)
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
    scope_ids: list[str],
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = scope_vdbs(scope_ids, accessible_vdbs)
    evidence = [_collection_evidence(vdb, task["id"], task["query"]) for vdb in selected_vdbs]
    return {"selected_vdbs": [str(v["id"]) for v in selected_vdbs]}, evidence


def _run_list_documents(
    task: dict[str, Any],
    user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    scope_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = scope_vdbs(scope_ids, accessible_vdbs)
    evidence: list[Evidence] = []
    for vdb in selected_vdbs:
        documents = backend_client.list_collection_documents(user_id, str(vdb["id"]))
        for document in documents:
            partial = (
                f" [partial summary: pages {_pages_text(document['summary_pages'])} only]"
                if document.get("summary_pages")
                else ""
            )
            content = f"{document['name']} ({document['status']}){partial}: {document['summary'] or 'no summary yet'}"
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
                        "evidence_kind": "document",
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
                metadata={
                    "document_name": vdb["name"],
                    "count": count,
                    "evidence_kind": "collection",
                },
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
    scope_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict, list[Evidence]]:
    selected_vdbs = scope_vdbs(scope_ids, accessible_vdbs)
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
                "evidence_kind": "document",
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
    _scope_ids: list[str],
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


def _run_time(
    task: dict[str, Any],
    _user_id: str,
    _accessible_vdbs: list[dict[str, Any]],
    _model: str | None,
    _scope_ids: list[str],
    _web_search_enabled: bool,
) -> tuple[dict[str, Any], list[Evidence]]:
    """Time tool: gives the LLM precise temporal context (current time to the second) and
    pre-computed relative periods (today, this week, last month, etc.) so it can reason about
    time-dependent queries. No backend call needed — pure computation."""
    ctx = build_time_context()
    content = format_time_context(ctx)
    evidence = [
        Evidence(
            id=str(uuid.uuid4()),
            task_id=task["id"],
            vdb_id="",
            source_id="",
            content=content,
            metadata={
                "evidence_kind": "time",
                "now": ctx["now"],
                "timezone": ctx["timezone"],
                "date": ctx["date"],
                "time": ctx["time"],
                "week_number": ctx["week_number"],
                "periods": ctx["periods"],
            },
            relevance_score=None,
            retrieval_query=task["query"],
        )
    ]
    return {"selected_vdbs": [], "results": []}, evidence


def _run_tabular_query(
    task: dict[str, Any],
    user_id: str,
    accessible_vdbs: list[dict[str, Any]],
    model: str | None,
    scope_ids: list[str],
    _web_search_enabled: bool,
    run_id: str | None = None,
) -> tuple[dict[str, Any], list[Evidence]]:
    """Tabular data analysis tool (#433): the model queries the tabular files of the selected collections in SQL,
    through the SQL worker, and corrects its queries from the errors it gets back - questions about aggregations,
    filters, counts or joins between files that vector search over text chunks can't answer.

    1. The tabular documents of each selected collection are listed by the backend (the permission barrier) and made
       a catalog: files, sheets, columns. A document with no typed copy is announced, never queried.
    2. The model's tool loop runs over the catalog (app/graph/services/tabular_query.py).
    3. Every call of the loop - the SQL and its result or its error - is in the evidence.

    If no model is configured or there is nothing to query, returns empty evidence - the gate will decide if
    the surviving tasks are enough. A SQL worker that does not answer fails the task, with a message that says so.
    """
    if model is None:
        logger.warning(f"Task {task['id']} requested tabular_query but no chat model is configured")
        return {"selected_vdbs": [], "results": []}, []

    selected_vdbs = scope_vdbs(scope_ids, accessible_vdbs)
    if not selected_vdbs:
        return {"selected_vdbs": [], "results": []}, []
    updates = {"selected_vdbs": [str(v["id"]) for v in selected_vdbs]}

    listings = []
    for vdb in selected_vdbs:
        documents = backend_client.list_tabular_documents(user_id, str(vdb["id"]))
        if documents:
            listings.append((vdb, documents))
    catalog = Catalog.build(listings, settings.TABULAR_MAX_FILES)
    if not catalog.files and not catalog.pending:
        return updates, []

    outcome = run_query_loop(task["query"], catalog, model, run_id) if catalog.files else LoopOutcome()
    if not outcome.succeeded:
        if outcome.stopped and outcome.calls:
            raise RuntimeError(f"Analyse des données impossible : {outcome.stopped}")
        if not catalog.pending:
            logger.info(f"No tabular query worked for task {task['id']}")
            return updates, []

    used = [file for file in catalog.files if file.ref in outcome.used_refs] or catalog.files[:1]
    first = used[0] if used else None
    last = outcome.succeeded[-1] if outcome.succeeded else None
    evidence = [
        Evidence(
            id=str(uuid.uuid4()),
            task_id=task["id"],
            vdb_id=first.collection_id if first else str(selected_vdbs[0]["id"]),
            source_id=first.document_id if first else "",
            content=format_tabular_evidence(task["query"], catalog, outcome),
            metadata={
                "document_name": first.name if first else "Fichiers tabulaires",
                "evidence_kind": "tabular",
                "sql": last.sql if last else None,
                "calls": [{"sql": c.sql, "ok": c.ok, "error": c.error, "rows": len(c.rows)} for c in outcome.calls],
                "row_count": len(last.rows) if last else 0,
                "truncated": last.truncated if last else False,
                # The charts drawn for this answer (#434): generate_answer puts the ones it forgets at the end.
                "charts": outcome.charts,
            },
            relevance_score=None,
            retrieval_query=task["query"],
        )
    ]
    # Each other file the queries read is a source that can be cited on its own: the calculation is above.
    for file in used[1:]:
        evidence.append(
            Evidence(
                id=str(uuid.uuid4()),
                task_id=task["id"],
                vdb_id=file.collection_id,
                source_id=file.document_id,
                content=f"Le fichier {file.name} a été lu par les requêtes ci-dessus (feuilles : "
                + ", ".join(sheet.name for sheet in file.sheets)
                + ").",
                metadata={"document_name": file.name, "evidence_kind": "tabular"},
                relevance_score=None,
                retrieval_query=task["query"],
            )
        )
    return updates, evidence


_RUNNERS = {
    "list_collections": lambda task, user_id, accessible_vdbs, model, scope_ids, web_search_enabled: (
        _run_list_collections(task, accessible_vdbs)
    ),
    "collection_summary": lambda task, user_id, accessible_vdbs, model, scope_ids, web_search_enabled: (
        _run_collection_summary(task, accessible_vdbs, scope_ids)
    ),
    "list_documents": _run_list_documents,
    "page_content": _run_page_content,
    "tabular_query": _run_tabular_query,
    "web_search": _run_web_search,
    "time": _run_time,
}


def research_task(state: ResearchTaskInput) -> dict[str, Any]:
    """Central research node (§11) - one call handles exactly one ResearchTask and knows nothing
    about the others. It orchestrates VDB routing + search/meta-lookups as plain service calls
    (§35: these are not themselves LangGraph nodes, only research_task is). `task["tool"]` picks
    which of those services actually runs - content search by default, or a knowledge-base
    introspection lookup (collection/document counts and summaries, page content) chosen by
    the plan. Every lookup still goes through the same accessible_vdbs permission
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
        if task["tool"] == "tabular_query":
            runner = partial(_run_tabular_query, run_id=run_id)
        updates, evidence = runner(
            task,
            user_id,
            state["accessible_vdbs"],
            state["chat_model"],
            state["scope_ids"],
            state["web_search_enabled"],
        )
        # Stamped centrally here (not in each runner) so every evidence-producing branch tags
        # itself the same way, once - lets a citation say which tool produced it (§ sources
        # panel: a "search" citation links to a real page/chunk, a meta-tool one is just
        # input/output, no page to link to).
        evidence = [{**e, "metadata": {**e["metadata"], "tool": task["tool"]}} for e in evidence]
        # Run-level, not part of the task itself - see AgentState.unexplored_vdb_ids.
        unexplored_vdb_ids = updates.pop("unexplored_vdb_ids", [])
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
            "unexplored_vdb_ids": unexplored_vdb_ids,
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
