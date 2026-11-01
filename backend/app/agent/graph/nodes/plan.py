from typing import Any

from app.agent.ask_user import GUIDANCE, free_text_question, render_questions, sanitize_questions
from app.agent.config import settings
from app.agent.graph.services.authoring import (
    CREATE_VERBS,
    NO_COLLECTION,
    NOT_MARKDOWN,
    collections_catalogue,
    create_clarification,
    documents_catalogue,
    edit_clarification,
)
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.llm import json_chat
from app.agent.graph.services.prompts import get_prompt
from app.agent.graph.services.scope import scope_ids
from app.agent.graph.services.tool_guide import (
    AUTHORING_CAPABILITIES,
    tool_guide,
    valid_tools,
)
from app.agent.graph.services.vdb_router import catalogue_entry
from app.agent.graph.state import AgentState, ResearchTask

_MODES = ("direct", "clarify", "help", "edit", "create", "search")

_SYSTEM_PROMPT = (
    "You are Muffin, an internal assistant that answers by searching the user's own knowledge base collections "
    "(and the web only when the user enabled it). You are the planner: read the user's current message, in light of "
    "the conversation so far, and decide everything that has to happen before an answer can be written. Reply only "
    'with one JSON object with the key "mode", one of:\n'
    '- "direct": answer now, without searching - a greeting, thanks, a question about you or what you can do (use '
    "the capabilities below, never invent one), or anything that needs none of the user's documents. Put the "
    'complete answer in "answer", in the user\'s language, short and friendly.\n'
    '- "clarify": the request is truly unanswerable without more information - only then. Give "questions": an '
    'array of objects with keys "question", "header", "multi_select" and "options" (array of objects with '
    '"label" and "description"). The user already selected the collections to query, so "the file", "the data" '
    "refer to them and are NOT ambiguous. Analytical questions on tabular data are NOT ambiguous either. When in "
    "doubt, search: an attempt is better than blocking the user. If the assistant's last message asked questions "
    'and this one answers them, do not clarify again: "standalone_query" combines the request with the answers.\n'
    '- "help": the user asks how to USE the Muffin application itself (where something is, how to share a '
    "collection, what a feature does) - never for a question whose answer is in their documents, and never for a "
    "request to actually do it.\n"
    '- "edit": the user asks to modify, add to, remove from or rewrite one of the documents listed under "Documents '
    'the user can edit" (only when that list is given). Give "document_id" (the one listed id the message names or '
    'clearly points to, else null), "candidates" (ids, only when it could mean several and nothing tells which) and '
    '"instruction" (the change, restated to stand on its own, in the user\'s own words and terms). Be conservative: '
    "a question about a document is a search, and a document that is not listed is not an edit.\n"
    '- "create": the user asks to write a new document, note or file to keep in one of the collections listed under '
    '"Collections the user may add a document to" (only when that list is given). Give "collection_id" (the one '
    'listed id the message names or clearly points to, else null), "candidates" (ids, when several could be meant), '
    '"markdown" (false only if the user asks for another format such as Word, PDF or Excel), "title" and '
    '"instruction" (what it must contain, in the user\'s own words and terms). Be conservative: a request for an '
    "answer in the chat is not a creation.\n"
    '- "search": anything that needs the user\'s documents or the tools below (the default).\n\n'
    'For "search", also give:\n'
    '- "standalone_query": the current message rewritten to stand on its own, resolving "it", "elle", "ce '
    'fichier" with the conversation; unchanged when it already does.\n'
    '- "queries": 1 to 4 independent searches, in an array of {"query": ..., "tool": ...}. A simple question is ONE '
    "query. Several only when the question really has several independent parts (a comparison: one query per "
    "side). They run in parallel, so none may depend on another's result.\n"
    '- "collections": the ids of the knowledge bases listed below that can hold the answer, chosen from their '
    "name and description (a nested one is shown with its path; choosing a collection also searches the ones "
    "below it). Leave it empty when you cannot tell: the search then covers every collection.\n"
    '- "complexity": "simple" (one fact, one source) or "complex" (comparison, synthesis, several sources).\n\n'
    "{guide}\n"
    "What you can do besides searching, to answer a question about yourself:\n{capabilities}"
)

# Added to whichever version of the prompt is in use (it is administrable, see get_prompt), so a version written
# before the questions with options still gets them.
_QUESTIONS_INSTRUCTION = f'\n\nFor "clarify", the questions follow these rules: {GUIDANCE}'

_MAX_QUERIES = 4
_HISTORY_TURNS = 6
_HISTORY_CHARS = 1500


def _fallback(query: str) -> dict[str, Any]:
    return {
        "mode": "search",
        "standalone_query": query,
        "queries": [{"query": query, "tool": "search"}],
        "collections": [],
        "complexity": "simple",
    }


def _history(state: AgentState) -> str:
    """The last turns only: older ones weigh on every call and rarely change what the user means now."""
    turns = state["messages"][:-1][-_HISTORY_TURNS:]
    return "\n".join(f"{m['role']}: {str(m['content'])[:_HISTORY_CHARS]}" for m in turns)


def _user_content(state: AgentState) -> str:
    by_id = {str(vdb["id"]): vdb for vdb in state["accessible_vdbs"]}
    knowledge_bases = "\n".join(str(catalogue_entry(vdb, by_id)) for vdb in state["catalogue"]) or "(none)"
    parts = []
    history = _history(state)
    if history:
        parts.append(f"Conversation so far:\n{history}")
    parts.append(f"Current message: {state['original_query']}")
    parts.append(f"Knowledge bases:\n{knowledge_bases}")
    pinned = [by_id[i]["name"] for i in state["pinned_vdb_ids"] if i in by_id]
    if pinned:
        parts.append(f"The user attached these collections to the message: {', '.join(pinned)}")
    if state["edit_candidates"]:
        parts.append(f"Documents the user can edit:\n{documents_catalogue(state['edit_candidates'])}")
    if state["create_candidates"]:
        parts.append(
            f"Collections the user may add a document to:\n{collections_catalogue(state['create_candidates'])}"
        )
    return "\n\n".join(parts)


def _queries(
    raw: Any, query: str, web_search_enabled: bool, disabled: frozenset[str] = frozenset()
) -> list[dict[str, str]]:
    allowed = valid_tools(web_search_enabled, disabled)
    found = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("query") or "").strip():
            continue
        tool = item.get("tool") if item.get("tool") in allowed else "search"
        found.append({"query": str(item["query"]).strip(), "tool": tool})
    return found[:_MAX_QUERIES] or [{"query": query, "tool": "search"}]


def _known(ids: Any, by_id: dict[str, Any]) -> list[str]:
    return [str(i) for i in ids if str(i) in by_id] if isinstance(ids, list) else []


def normalize_plan(raw: Any, state: AgentState) -> dict[str, Any]:
    """The plan as the graph reads it. Whatever the model returned, it can only narrow what the backend allowed: an id
    it names that is not in the lists the backend gave is dropped, and a plan it could not make is a plain search."""
    query = state["original_query"]
    if not isinstance(raw, dict) or raw.get("mode") not in _MODES:
        return _fallback(query)

    mode = raw["mode"]
    plan: dict[str, Any] = {"mode": mode}
    standalone = str(raw.get("standalone_query") or "").strip() or query
    accessible_ids = {str(vdb["id"]) for vdb in state["accessible_vdbs"]}

    if mode == "direct":
        answer = str(raw.get("answer") or "").strip()
        return {"mode": "direct", "answer": answer} if answer else _fallback(query)
    if mode == "clarify":
        questions = sanitize_questions(raw.get("questions")) or [
            free_text_question(str(raw.get("clarification_question") or "Could you clarify your request?"))
        ]
        # Nobody to ask (a run started by a program), or already asked too often in a row: carry on and say what is
        # assumed instead of questioning the user in a loop (#344).
        if not state["interactive"] or state["question_rounds"] >= settings.MAX_QUESTION_ROUNDS:
            return {**_fallback(query), "standalone_query": standalone, "must_assume": True}
        return {"mode": "clarify", "questions": questions}
    if mode == "help":
        return {"mode": "help", "standalone_query": standalone}
    if mode == "edit":
        documents = {d["document_id"]: d for d in state["edit_candidates"]}
        if not documents:
            return _fallback(query)
        chosen = documents.get(str(raw.get("document_id") or ""))
        instruction = str(raw.get("instruction") or "").strip() or query
        if chosen is not None:
            return {"mode": "edit", "document_id": chosen["document_id"], "instruction": instruction}
        candidates = _known(raw.get("candidates"), documents)
        # Said "edit" but named nothing it was offered: an ordinary question, never a guess at which document to change.
        return {"mode": "edit", "candidates": candidates} if len(candidates) >= 2 else _fallback(query)
    if mode == "create":
        collections = {c["collection_id"]: c for c in state["create_candidates"]}
        if raw.get("markdown") is False:
            return {"mode": "create", "refused": NOT_MARKDOWN}
        if not state["create_candidates"]:
            # The message looked like a request to create (the gate let the plan see it) but there is nowhere to put it.
            return {"mode": "create", "refused": NO_COLLECTION} if CREATE_VERBS.search(query) else _fallback(query)
        chosen = collections.get(str(raw.get("collection_id") or ""))
        if chosen is None and len(collections) == 1:
            chosen = next(iter(collections.values()))
        title = str(raw.get("title") or "").strip()
        instruction = str(raw.get("instruction") or "").strip() or query
        if chosen is None:
            return {"mode": "create", "candidates": _known(raw.get("candidates"), collections)}
        return {"mode": "create", "collection_id": chosen["collection_id"], "title": title, "instruction": instruction}

    plan |= {
        "standalone_query": standalone,
        "queries": _queries(
            raw.get("queries"), standalone, state["web_search_enabled"], frozenset(state.get("disabled_tools") or ())
        ),
        "collections": _known(raw.get("collections"), dict.fromkeys(accessible_ids)),
        "complexity": "complex" if raw.get("complexity") == "complex" else "simple",
    }
    return plan


def _tasks(plan: dict[str, Any]) -> list[ResearchTask]:
    return [
        ResearchTask(
            id=f"task-{index}",
            query=item["query"],
            intent=None,
            tool=item["tool"],
            dependencies=[],
            status="ready",
            candidate_vdbs=[],
            selected_vdbs=[],
            search_queries=[],
            results=[],
            error=None,
        )
        for index, item in enumerate(plan["queries"], start=1)
    ]


async def plan(state: AgentState) -> dict[str, Any]:
    """The one call that decides what happens (the replacement of detect_edit, detect_create, analyze_query,
    decompose_query and the choice of collections of each task): answer now, ask, explain the application, edit or
    create a document, or search - with which queries, tools and collections. Everything after it is code."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}

    await set_activity(run_id, "plan", "Analyzing your question")
    await emit(run_id, "query_analysis_started", {"query": state["original_query"]})

    model = state["chat_model"]
    prompt_usages: list[str] = []
    if model is None:
        raw: Any = None
    else:
        template, prompt_version_id = await get_prompt("plan", fallback=_SYSTEM_PROMPT)
        if prompt_version_id:
            prompt_usages.append(prompt_version_id)
        guide = tool_guide(state["web_search_enabled"], frozenset(state.get("disabled_tools") or ()))
        system_prompt = template.replace("{guide}", guide).replace("{capabilities}", AUTHORING_CAPABILITIES)
        raw = await json_chat(model, system_prompt + _QUESTIONS_INSTRUCTION, _user_content(state), fallback=None)

    plan_ = normalize_plan(raw, state)
    mode = plan_["mode"]
    standalone = plan_.get("standalone_query") or state["original_query"]
    await emit(run_id, "query_analysis_completed", {"analysis": {k: v for k, v in plan_.items() if k != "answer"}})

    updates: dict[str, Any] = {
        "plan": plan_,
        "contextualized_query": standalone,
        "prompt_usages": prompt_usages,
        "must_assume": bool(plan_.get("must_assume")),
        "query_analysis": {
            "intent": {"direct": "identity", "help": "help"}.get(mode, "lookup"),
            "complexity": plan_.get("complexity", "simple"),
            "requires_multiple_sources": len(plan_.get("queries", [])) > 1,
            "standalone_query": standalone,
        },
        "needs_grounding": plan_.get("complexity") == "complex" or len(plan_.get("queries", [])) > 1,
    }
    if mode == "direct":
        updates |= {"answer": plan_["answer"], "citations": []}
    elif mode == "clarify":
        text = render_questions(plan_["questions"])
        await emit(run_id, "clarification_requested", {"question": text, "questions": plan_["questions"]})
        updates |= {"answer": text, "citations": [], "questions": plan_["questions"]}
    elif mode == "edit":
        updates["edit_target"] = await _edit_target(plan_, state)
    elif mode == "create":
        updates["create_target"] = await _create_target(plan_, state)
    elif mode == "search":
        updates["research_tasks"] = _tasks(plan_)
        updates["scope_ids"] = scope_ids(plan_["collections"], state["pinned_vdb_ids"], state["accessible_vdbs"])
    return updates


async def _edit_target(plan_: dict[str, Any], state: AgentState) -> dict[str, Any]:
    documents = state["edit_candidates"]
    if "document_id" not in plan_:
        await emit(state["run_id"], "edit_target_ambiguous", {"candidates": plan_["candidates"]})
        return {"clarification": edit_clarification(documents, plan_["candidates"])}
    chosen = next(d for d in documents if d["document_id"] == plan_["document_id"])
    await emit(
        state["run_id"], "edit_target_detected", {"document_id": chosen["document_id"], "document": chosen["name"]}
    )
    return {
        "document_id": chosen["document_id"],
        "document_name": chosen["name"],
        "collection_id": chosen["collection_id"],
        "instruction": plan_["instruction"],
    }


async def _create_target(plan_: dict[str, Any], state: AgentState) -> dict[str, Any]:
    if "refused" in plan_:
        await emit(
            state["run_id"],
            "create_refused",
            {"reason": "not_markdown" if plan_["refused"] == NOT_MARKDOWN else "no_collection"},
        )
        return {"clarification": plan_["refused"]}
    collections = state["create_candidates"]
    if "collection_id" not in plan_:
        await emit(state["run_id"], "create_target_ambiguous", {"candidates": plan_["candidates"]})
        return {"clarification": create_clarification(collections, plan_["candidates"])}
    chosen = next(c for c in collections if c["collection_id"] == plan_["collection_id"])
    await emit(
        state["run_id"],
        "create_target_detected",
        {"collection_id": chosen["collection_id"], "collection": chosen["name"]},
    )
    return {
        "collection_id": chosen["collection_id"],
        "collection_name": chosen["name"],
        "title": plan_["title"],
        "instruction": plan_["instruction"],
    }
