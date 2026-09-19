from typing import Any

from app.backend_client import backend_client
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "Answer the user's query using only the given evidence excerpts. Cite each claim with its excerpt id "
    "in brackets, e.g. [abc123]. Never invent facts not supported by the excerpts. If the evidence notes "
    "some information is missing, say so plainly instead of guessing or narrating your internal process. "
    'If the query asks for a count (e.g. "how many collections/documents"), each excerpt below already '
    "represents one distinct item unless it says otherwise - count the excerpts and state that number "
    "directly. Never refuse to count just because no single excerpt states the total as a sentence."
)


def generate_answer(state: AgentState) -> dict[str, Any]:
    """Final answer generation (§22). Grounding in the given evidence is enforced structurally,
    not just requested: no excerpts means no citations means an explicit "couldn't find" answer,
    never a call to the model asked to answer anyway."""
    run_id = state["run_id"]
    if is_cancelled(run_id):
        return {"cancelled": True}

    set_activity(run_id, "generate_answer", "Generating the answer")
    emit(run_id, "answer_generation_started")
    context = state["answer_context"]
    model = state["chat_model"]

    if model is None:
        return {"answer": "No language model is available to answer this query right now.", "citations": []}

    if not context["excerpts"]:
        return {
            "answer": "I couldn't find any relevant information in your accessible knowledge bases to answer "
            "this query.",
            "citations": [],
        }

    evidence_block = "\n\n".join(f"[{e['id']}] (source: {e['source']})\n{e['content']}" for e in context["excerpts"])
    missing_note = (
        f"\n\nNote: the following could not be established from accessible sources: {context['missing_information']}"
        if context["coverage_insufficient"]
        else ""
    )
    user_content = f"Query: {state['contextualized_query']}\n\nEvidence:{missing_note}\n\n{evidence_block}"
    answer = backend_client.llm_chat(
        model,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    citations = [
        {
            "evidence_id": e["id"],
            "source": e["source"],
            "vdb_id": e["vdb_id"],
            "tool": e["tool"],
            "document_id": e["document_id"],
            "chunk_id": e["chunk_id"],
            "page_number": e["page_number"],
            "url": e["url"],
            "query": e["query"],
            "content": e["content"],
        }
        for e in context["excerpts"]
    ]
    emit(run_id, "answer_generation_completed", {"citation_count": len(citations)})
    return {"answer": answer, "citations": citations}
