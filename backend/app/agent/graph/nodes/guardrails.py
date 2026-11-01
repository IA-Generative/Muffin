from typing import Any

from app.agent.backend_client import backend_client
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.state import AgentState

OUTCOME_BLOCK = "block"
OUTCOME_REDACTION = "continue_with_redaction"


async def guardrails(state: AgentState) -> dict[str, Any]:
    """The guardrails on the input (#516): what the request is checked against before anything of it goes to a model.
    Runs beside `prepare`, which reads no text, and is waited for by `prepare_request`, which does: so it adds no time
    when the guardrails are faster than the discovery of the collections - and none at all when there is none.

    What the person wrote stays theirs in the conversation. What goes on is `original_query` and the messages of the
    state, which are the request as it was masked when a guardrail redacts. Nothing but counts goes in the events: not
    which guardrail, not why."""
    run_id = state["run_id"]
    # `cancelled` is `prepare`'s to write: two nodes of a step writing it would be a conflict.
    if await is_cancelled(run_id):
        return {}
    await set_activity(run_id, "guardrails", "Vérification de la demande")
    await emit(run_id, "guardrail_started")
    decision = await backend_client.check_guardrails(run_id)
    await emit(
        run_id,
        "guardrail_completed",
        {"outcome": decision["outcome"], "checked": decision["checked"], "flagged": decision["flagged"]},
    )
    update: dict[str, Any] = {"guardrail": decision}
    if decision["outcome"] == OUTCOME_REDACTION:
        masked = decision["query"]
        update |= {
            "original_query": masked,
            "contextualized_query": masked,
            "messages": [*state["messages"][:-1], {"role": "user", "content": masked}],
        }
    return update


async def blocked(state: AgentState) -> dict[str, Any]:
    """The request was stopped: the answer is the refusal, written by the guardrails and never the rule. A normal answer
    of the conversation - the run is completed, not failed - and no model, no search, no web was reached."""
    decision = state["guardrail"]
    await emit(state["run_id"], "guardrail_blocked", {"checked": decision["checked"], "flagged": decision["flagged"]})
    return {
        "answer": decision["message"] or "",
        "citations": [],
        "needs_grounding": False,
        "execution_status": "completed",
    }
