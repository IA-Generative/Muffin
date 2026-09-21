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
    capabilities = _BASE_TOOL_GUIDE + (_WEB_SEARCH_TOOL_GUIDE if state["web_search_enabled"] else "")

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
