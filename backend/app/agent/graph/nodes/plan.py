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
from app.agent.graph.services.memory import MEMORY_ACTIONS, MEMORY_KINDS, MEMORY_PLAN_INSTRUCTION
from app.agent.graph.services.prompts import get_prompt
from app.agent.graph.services.scope import scope_ids
from app.agent.graph.services.tool_guide import (
    AUTHORING_CAPABILITIES,
    CALL_TOOL,
    external_tools_guide,
    tool_guide,
    valid_tools,
)
from app.agent.graph.services.vdb_router import catalogue_entry
from app.agent.graph.state import AgentState, ResearchTask

_MODES = ("direct", "clarify", "help", "edit", "create", "memory", "search")

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

# Added only when the run may consult other assistants (#531): part of the plan's own call, so it costs none.
_CONSULT_INSTRUCTION = (
    '\n\nOther assistants you may consult are listed below as "Assistants". Each one answers from its own knowledge '
    'bases. For a query that clearly belongs to one of them, add "assistant": its id to that query: it is then '
    "searched in that assistant's knowledge bases and not in yours. Do it only when it is clearly better placed "
    "than your own knowledge bases; otherwise leave it out. Use only the ids listed."
)

_MAX_QUERIES = 4
_HISTORY_TURNS = 6
_HISTORY_CHARS = 1500

# Added only when the message carries images (#512). The plan is made by a model that does not see them - only the model
# that writes the answer does - so it is told how many there are, and that a question about them needs no search.
_IMAGES_INSTRUCTION = (
    "\n\nThe user attached image(s) to this message. You cannot see them: the model that writes the answer will. Never "
    'answer yourself ("direct") nor ask what the image shows. If the question is about the image alone, choose '
    '"search" with no query at all. Add queries only for what must also be looked up in the knowledge bases.'
)


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
    if state.get("images"):
        current = [image for image in state["images"] if image["current"]]
        if current:
            parts.append(f"The user attached {len(current)} image(s) to this message.")
        else:
            parts.append(
                f"The user attached {len(state['images'])} image(s) to the previous message: this message may be a "
                "follow-up about them."
            )
    parts.append(f"Knowledge bases:\n{knowledge_bases}")
    if state.get("consultable_assistants"):
        listed = "\n".join(
            str({"id": a["id"], "name": a["name"], "description": a["description"]})
            for a in state["consultable_assistants"]
        )
        parts.append(f"Assistants:\n{listed}")
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
    raw: Any,
    query: str,
    web_search_enabled: bool,
    disabled: frozenset[str] = frozenset(),
    consultable: dict[str, dict[str, Any]] | None = None,
    available_tools: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The plan's queries, each with a tool that is allowed. A query may be put to an assistant the run may consult
    (#531): only one of those listed counts - any other id is dropped, the query then being the run's own - and the
    tools that assistant turns off are off for that query too."""
    consultable = consultable or {}
    available_tools = available_tools or {}
    found = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not str(item.get("query") or "").strip():
            continue
        consulted = consultable.get(str(item.get("assistant") or ""))
        off = disabled | frozenset(consulted["disabled_tools"]) if consulted else disabled
        allowed = valid_tools(web_search_enabled, off, external=bool(available_tools))
        tool = item.get("tool") if item.get("tool") in allowed else "search"
        entry: dict[str, Any] = {"query": str(item["query"]).strip(), "tool": tool}
        if tool == CALL_TOOL:
            # A call is only ever to a tool the person was offered, with arguments that fit its schema - checked
            # here, in code, whatever the model wrote. Otherwise the query is a plain search.
            arguments = _checked_call(item, available_tools)
            if arguments is None:
                entry["tool"] = "search"
                found.append(entry)
                continue
            entry |= arguments
        # Only a search of content goes to an assistant: a tool that lists or summarises has no business in its scope.
        if consulted and tool == "search":
            entry["assistant"] = str(consulted["id"])
        found.append(entry)
    return found[:_MAX_QUERIES] or [{"query": query, "tool": "search"}]


def _checked_call(item: dict[str, Any], available: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """{"tool_ref", "arguments"} if the model named a tool it was offered and gave arguments that fit its schema."""
    import jsonschema

    tool = available.get(str(item.get("ref") or ""))
    arguments = item.get("arguments", {})
    if tool is None or not isinstance(arguments, dict):
        return None
    try:
        jsonschema.validate(arguments, tool["input_schema"])
    except jsonschema.ValidationError:
        return None
    except jsonschema.SchemaError:
        pass  # a schema written badly by a server: the server's own checks decide
    return {"tool_ref": tool["ref"], "arguments": arguments}


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
    if mode == "memory":
        action = str(raw.get("action") or "")
        text = str(raw.get("text") or "").strip()
        kind = str(raw.get("kind") or "")
        # Said "memory" where the memory is not offered, or for something it cannot do: an ordinary question.
        if (state.get("memory") or {}).get("state") == "suspended" or action not in MEMORY_ACTIONS:
            return _fallback(query)
        if action != "show" and not text:
            return _fallback(query)
        return {"mode": "memory", "action": action, "kind": kind if kind in MEMORY_KINDS else "fact", "text": text}
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
        # A question about an image alone looks nothing up: the plan said so with no query at all (#512). Without an
        # image an empty list is not a plan, and the question itself is searched.
        "queries": []
        if state.get("images") and raw.get("queries") == []
        else _queries(
            raw.get("queries"),
            standalone,
            state["web_search_enabled"],
            frozenset(state.get("disabled_tools") or ()),
            {a["id"]: a for a in state.get("consultable_assistants") or []},
            {t["ref"]: t for t in state.get("available_tools") or []},
        ),
        "collections": _known(raw.get("collections"), dict.fromkeys(accessible_ids)),
        "complexity": "complex" if raw.get("complexity") == "complex" else "simple",
    }
    return plan


def _tasks(plan: dict[str, Any], consultable: dict[str, dict[str, Any]] | None = None) -> list[ResearchTask]:
    consultable = consultable or {}
    tasks = []
    for index, item in enumerate(plan["queries"], start=1):
        task = ResearchTask(
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
        if item.get("tool_ref"):
            task |= {"tool_ref": item["tool_ref"], "arguments": item.get("arguments") or {}}
        consulted = consultable.get(item.get("assistant", ""))
        if consulted:
            task |= {
                "assistant_id": consulted["id"],
                "assistant_name": consulted["name"],
                "scope_ids": list(consulted["collection_ids"]),
            }
        tasks.append(task)
    return tasks


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
        guide = tool_guide(
            state["web_search_enabled"], frozenset(state.get("disabled_tools") or ())
        ) + external_tools_guide(state.get("available_tools") or [])
        system_prompt = template.replace("{guide}", guide).replace("{capabilities}", AUTHORING_CAPABILITIES)
        instructions = _QUESTIONS_INSTRUCTION + (_CONSULT_INSTRUCTION if state.get("consultable_assistants") else "")
        if state.get("images"):
            instructions += _IMAGES_INSTRUCTION
        if (state.get("memory") or {}).get("state", "suspended") != "suspended":
            instructions += MEMORY_PLAN_INSTRUCTION
        raw = await json_chat(model, system_prompt + instructions, _user_content(state), fallback=None)

    plan_ = normalize_plan(raw, state)
    # A plan that answers or asks without the images would answer without having seen them: the run goes on to the model
    # that reads them, with whatever search the plan asked for - none, for a question about the image alone (#512).
    if state.get("images") and plan_["mode"] in ("direct", "clarify"):
        plan_ = {**plan_, "mode": "search", "queries": [], "collections": plan_.get("collections", [])}
    mode = plan_["mode"]
    standalone = plan_.get("standalone_query") or state["original_query"]
    # What the person asked to remember is nowhere in the events: only that the plan chose to handle their memory.
    await emit(
        run_id,
        "query_analysis_completed",
        {"analysis": {k: v for k, v in plan_.items() if k not in ("answer", "text")}},
    )

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
        "needs_grounding": (plan_.get("complexity") == "complex" or len(plan_.get("queries", [])) > 1)
        # What the model says of an image is not in the evidence the check reads (#512).
        and not state.get("images"),
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
        updates["research_tasks"] = _tasks(plan_, {a["id"]: a for a in state.get("consultable_assistants") or []})
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
