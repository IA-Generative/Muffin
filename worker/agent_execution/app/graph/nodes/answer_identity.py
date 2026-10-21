from typing import Any

from app.backend_client import backend_client
from app.graph.nodes.decompose_query import _BASE_TOOL_GUIDE, _WEB_SEARCH_TOOL_GUIDE
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.prompts import get_prompt
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "You are Muffin, an internal assistant that answers questions by searching the user's own knowledge base "
    "collections (and the web, only when the user has explicitly enabled it for this conversation). The user "
    "is asking about you rather than about their documents - introduce yourself briefly by name, then describe "
    "what you can do using only the capabilities listed below. Never invent a capability that isn't listed, "
    "never claim general knowledge beyond what those tools can actually do. Keep the answer short, friendly, "
    "and respond in the same language as the user's query."
)

# What the agent can do besides searching, described for a user who asks "what can you do?" or "can
# you edit/create a file?". Kept here rather than in the planner's tool guide: these aren't tools the
# research planner picks from, they are separate paths (detect_edit / detect_create) of the graph.
_AUTHORING_CAPABILITIES = (
    "Writing in the user's collections (the user always reviews and validates first - nothing is "
    "written to a collection without their approval):\n"
    "- Modify an existing living document (an ODT or Markdown document in one of the user's own "
    "collections): add, rewrite, remove or correct content. The change is shown as a proposal to "
    "compare with the current version, then validate, adjust or refuse.\n"
    "- Create a new document in one of the user's own collections - Markdown (.md) only, never Word, "
    "ODT, PDF or Excel. It is written from the request and the conversation, without searching the "
    "collections, and shown as a proposal to create or refuse.\n"
    "Both are only possible in collections the user owns.\n"
    "Explaining how to use the Muffin application itself (collections, adding documents, sharing, "
    'living documents, settings...) when asked "how do I...?".'
)


def answer_identity(state: AgentState) -> dict[str, Any]:
    """Answers a question about the agent itself (§ issue #99) - short-circuits straight to a
    canned-but-versioned answer instead of letting "qui es-tu ?" fall through decompose_query
    and search the user's collections for nothing (§ issue #97's original complaint)."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "answer_identity", "Introducing myself")
    emit(run_id, "identity_answer_started")

    model = state["chat_model"]
    # Same tool guide decompose_query itself shows the planner - capabilities described here
    # stay in sync with what the agent can actually do without listing them by hand twice, and
    # web_search is only ever mentioned when this run actually opted into it (§ security, same
    # reasoning as decompose_query._WEB_SEARCH_TOOL_GUIDE).
    capabilities = (
        _BASE_TOOL_GUIDE
        + (_WEB_SEARCH_TOOL_GUIDE if state["web_search_enabled"] else "")
        + "\n"
        + _AUTHORING_CAPABILITIES
    )

    if model is None:
        answer = "I'm Muffin, an internal document search assistant."
        prompt_version_id = None
    else:
        system_prompt, prompt_version_id = get_prompt("agent_identity", fallback=_SYSTEM_PROMPT)
        user_content = f"Query: {state['contextualized_query']}\n\nAvailable capabilities:\n{capabilities}"
        result = backend_client.llm_chat_with_usage(
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        answer = result["content"]

    emit(run_id, "identity_answer_completed")
    return {
        "answer": answer,
        "citations": [],
        "prompt_usages": [prompt_version_id] if prompt_version_id else [],
    }
