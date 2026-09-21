import time
from typing import Any

from app.backend_client import backend_client
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.prompts import get_prompt
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "Answer the user's query using only the given evidence excerpts. Cite each claim with its excerpt id "
    "in brackets, e.g. [abc123]. Never invent facts not supported by the excerpts. If the evidence notes "
    "some information is missing, say so plainly instead of guessing or narrating your internal process. "
    'If the query asks for a count (e.g. "how many collections/documents"), each excerpt below already '
    "represents one distinct item unless it says otherwise - count the excerpts and state that number "
    "directly. Never refuse to count just because no single excerpt states the total as a sentence.\n\n"
    "Formatting:\n"
    "- Use markdown for structure: **bold** for key numbers, `code` for column names.\n"
    "- When the evidence contains tabular results (SQL query results with rows and columns), "
    "format the answer as a markdown table with proper headers and alignment.\n"
    "- When listing multiple items (e.g. top 5, rankings), use a markdown table with a rank column.\n"
    "- For a single value answer (e.g. a count, an average), state it directly and prominently in bold.\n"
    "- For grouped/comparison results, always use a markdown table - never a plain text list.\n"
    "- Keep the answer concise: lead with the direct answer, then the supporting table or breakdown.\n"
    "- Respond in the same language as the user's query."
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
        return {
            "answer": "No language model is available to answer this query right now.",
            "citations": [],
        }

    if not context["excerpts"]:
        return {
            "answer": "I couldn't find any relevant information in your accessible knowledge bases to answer "
            "this query.",
            "citations": [],
        }

    system_prompt, prompt_version_id = get_prompt("generate_answer", fallback=_SYSTEM_PROMPT)
    evidence_block = "\n\n".join(f"[{e['id']}] (source: {e['source']})\n{e['content']}" for e in context["excerpts"])
    missing_note = (
        f"\n\nNote: the following could not be established from accessible sources: {context['missing_information']}"
        if context["coverage_insufficient"]
        else ""
    )
    user_content = f"Query: {state['contextualized_query']}\n\nEvidence:{missing_note}\n\n{evidence_block}"
    start = time.monotonic()
    result = backend_client.llm_chat_with_usage(
        model,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    answer = result["content"]
    prompt_tokens = result.get("prompt_tokens")
    completion_tokens = result.get("completion_tokens")
    citations = [
        {
            "evidence_id": e["id"],
            "source": e["source"],
            "vdb_id": e["vdb_id"],
            "tool": e["tool"],
            "evidence_kind": e["evidence_kind"],
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
    return {
        "answer": answer,
        "citations": citations,
        "answer_latency_ms": latency_ms,
        "answer_prompt_tokens": prompt_tokens,
        "answer_completion_tokens": completion_tokens,
        "prompt_usages": [prompt_version_id] if prompt_version_id else [],
    }
