from typing import Any

from app.agent.backend_client import backend_client
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.state import AgentState


async def memory_command(state: AgentState) -> dict[str, Any]:
    """What the person asked of their memory in the chat - remember, forget, show (#282). Carried out by the backend
    under the rules of the page "Ma mémoire" - what is never kept, the limits, the guardrails - and answered in words,
    from what was really done: no model writes this answer, so it cannot say more than happened. The events say what
    was asked and what came of it, never what was said."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}

    plan = state["plan"]
    await set_activity(run_id, "memory", "Updating your memory")
    outcome = await backend_client.memory_command(run_id, plan["action"], plan["kind"], plan["text"])
    await emit(run_id, "memory_command_completed", {"action": plan["action"], "outcome": outcome["outcome"]})
    return {"answer": outcome["message"], "citations": []}
