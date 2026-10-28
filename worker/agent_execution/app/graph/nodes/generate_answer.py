import time
from typing import Any

from loguru import logger

from app.ask_user import NOBODY_TO_ASK
from app.backend_client import backend_client
from app.graph.services.citations import CITATION_RULE, RETRY_MESSAGE, cited_ids, without_invented_markers
from app.graph.services.events import emit, is_cancelled, set_activity
from app.graph.services.prompts import get_prompt
from app.graph.services.vdb_router import collection_path, collection_path_names
from app.graph.state import AgentState

_SYSTEM_PROMPT = (
    "Answer the user's query using only the given evidence excerpts. Cite each claim with its excerpt id "
    "in brackets, e.g. [abc123]. Never invent facts not supported by the excerpts. If the evidence notes "
    "some information is missing, say so plainly instead of guessing or narrating your internal process. "
    "If the evidence suggests enabling web search, relay that suggestion in your answer (translated into "
    "the response's language if needed) instead of dropping it. "
    'If the query asks for a count (e.g. "how many collections/documents"), each excerpt below already '
    "represents one distinct item unless it says otherwise - count the excerpts and state that number "
    "directly. Never refuse to count just because no single excerpt states the total as a sentence.\n\n"
    "Formatting:\n"
    "- Use markdown for structure: **bold** for key numbers, `code` for column names.\n"
    "- When the evidence contains tabular results (SQL query results with rows and columns), "
    "format the answer as a markdown table with proper headers and alignment.\n"
    "- When the evidence contains a chart (a markdown image, ![title](url)), put that image in the answer exactly as "
    "written, where it illustrates the point, and describe in a sentence what it shows.\n"
    "- When listing multiple items (e.g. top 5, rankings), use a markdown table with a rank column.\n"
    "- For a single value answer (e.g. a count, an average), state it directly and prominently in bold.\n"
    "- For grouped/comparison results, always use a markdown table - never a plain text list.\n"
    "- Keep the answer concise: lead with the direct answer, then the supporting table or breakdown.\n"
    "- Respond in the same language as the user's query."
)


_PARTIAL_PUBLISH_INTERVAL_SECONDS = 0.4


def _write_answer(run_id: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Has the model write the answer, publishing the text written so far (at most every
    _PARTIAL_PUBLISH_INTERVAL_SECONDS) so the chat shows it while it is still coming. Same result as
    llm_chat_with_usage. A stream that fails before anything was written falls back to the plain call,
    so streaming can never be the reason an answer is lost."""
    text = ""
    prompt_tokens = completion_tokens = None
    last_published = 0.0
    try:
        backend_client.set_partial_answer(run_id, "")
        for item in backend_client.llm_chat_stream(model, messages):
            if item.get("done"):
                prompt_tokens, completion_tokens = item.get("prompt_tokens"), item.get("completion_tokens")
                continue
            text += item.get("delta", "")
            now = time.monotonic()
            if now - last_published >= _PARTIAL_PUBLISH_INTERVAL_SECONDS:
                backend_client.set_partial_answer(run_id, text)
                last_published = now
    except Exception:
        if text:
            raise
        logger.exception("Streaming the answer failed, asking for it in one piece instead")
        return backend_client.llm_chat_with_usage(model, messages)
    return {"content": text, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


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

    # Only worth suggesting when the run never had the option in the first place - if web search
    # was already on and still came up short, there's nothing left to point the user toward.
    web_search_hint = (
        " You could try enabling web search to look this up on the internet." if not state["web_search_enabled"] else ""
    )

    unexplored = _unexplored_paths(state)
    if not context["excerpts"]:
        go_further_hint = (
            f" Some sub-collections were not searched ({', '.join(unexplored)}) - you can ask to go further."
            if unexplored
            else ""
        )
        return {
            "answer": "I couldn't find any relevant information in your accessible knowledge bases to answer "
            f"this query.{web_search_hint}{go_further_hint}",
            "citations": [],
        }

    system_prompt, prompt_version_id = get_prompt("generate_answer", fallback=_SYSTEM_PROMPT)
    # Appended here, not in the prompt (administrable, see get_prompt): an overridden prompt keeps the rule (#402).
    system_prompt += CITATION_RULE
    evidence_block = "\n\n".join(
        f"[{e['id']}] (source: {e['source'] or e['tool']})\n{e['content']}" for e in context["excerpts"]
    )
    missing_note = (
        f"\n\nNote: the following could not be established from accessible sources: "
        f"{context['missing_information']}.{web_search_hint}"
        if context["coverage_insufficient"]
        else ""
    )
    # In the evidence itself rather than the system prompt (administrable, see get_prompt), so an
    # overridden prompt still gets it - same as missing_note above.
    exploration_note = (
        "\n\nNote: the search stopped before the sub-collections of these collections: "
        f"{'; '.join(unexplored)}. End the answer with one short sentence telling the user they can ask to "
        "go further into them."
        if unexplored
        else ""
    )
    # Same reasoning as exploration_note: nobody could be asked what the request left open (#344).
    assumption_note = (
        f"\n\nNote: {NOBODY_TO_ASK} Begin the answer with one short sentence stating them."
        if state.get("must_assume")
        else ""
    )
    user_content = (
        f"Query: {state['contextualized_query']}\n\nEvidence:{missing_note}{exploration_note}{assumption_note}"
        f"\n\n{evidence_block}"
    )
    start = time.monotonic()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    result = _write_answer(run_id, model, messages)
    prompt_tokens = result.get("prompt_tokens")
    completion_tokens = result.get("completion_tokens")
    valid_ids = {e["id"] for e in context["excerpts"]}
    written = without_invented_markers(result["content"], valid_ids)
    if not cited_ids(written, valid_ids):
        # Evidence was given and the answer cites none of it (#402): the model is asked once to write it again with its
        # citations. If it still cites nothing, the answer stands and the interface says that it has no source.
        logger.warning(f"Run {run_id}: the answer cites no evidence, asking for it again")
        emit(run_id, "answer_citations_retry")
        retry = backend_client.llm_chat_with_usage(
            model,
            [*messages, {"role": "assistant", "content": written}, {"role": "user", "content": RETRY_MESSAGE}],
        )
        retried = without_invented_markers(retry["content"], valid_ids)
        prompt_tokens = (prompt_tokens or 0) + (retry.get("prompt_tokens") or 0) or None
        completion_tokens = (completion_tokens or 0) + (retry.get("completion_tokens") or 0) or None
        if cited_ids(retried, valid_ids):
            written = retried
        else:
            logger.warning(f"Run {run_id}: the answer still cites no evidence")
    cited = set(cited_ids(written, valid_ids))
    latency_ms = int((time.monotonic() - start) * 1000)
    answer = with_missing_charts(written, context["excerpts"])
    by_id = {str(vdb["id"]): vdb for vdb in state["accessible_vdbs"]}
    citations = [
        {
            "evidence_id": e["id"],
            "source": e["source"],
            "vdb_id": e["vdb_id"],
            # Names from the root down to the collection (#220), only through collections this
            # user can read - empty for a citation not tied to one (web search, time).
            "vdb_path": collection_path_names(by_id[e["vdb_id"]], by_id) if e["vdb_id"] in by_id else [],
            "tool": e["tool"],
            "evidence_kind": e["evidence_kind"],
            "document_id": e["document_id"],
            "chunk_id": e["chunk_id"],
            # Whether the answer cites this excerpt or it was only consulted (#402): the interface shows the cited.
            "cited": e["id"] in cited,
            # Where a cited question-answer pair comes from (#351): the document, page and passage to open.
            "qa_source": e.get("qa_source"),
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


def with_missing_charts(answer: str, excerpts: list[dict[str, Any]]) -> str:
    """The answer, with at the end every chart drawn for it that it does not show (#434).

    The model is told to put each chart in its answer, but one that was drawn and then forgotten would be paid for and
    never seen."""
    shown = answer
    missing: list[str] = []
    for excerpt in excerpts:
        for chart in excerpt.get("charts", []):
            if chart["url"] not in shown:
                missing.append(chart["markdown"])
                shown += chart["url"]
    return answer if not missing else answer.rstrip() + "\n\n" + "\n\n".join(missing)


def _unexplored_paths(state: AgentState) -> list[str]:
    """Readable paths of the collections whose sub-collections the search didn't get to (#219),
    only those still in the accessible set."""
    by_id = {str(vdb["id"]): vdb for vdb in state["accessible_vdbs"]}
    unexplored_ids = dict.fromkeys(state.get("unexplored_vdb_ids") or [])
    return [collection_path(by_id[vdb_id], by_id) for vdb_id in unexplored_ids if vdb_id in by_id]
