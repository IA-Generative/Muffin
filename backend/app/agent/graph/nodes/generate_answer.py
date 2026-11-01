import base64
import time
from typing import Any

from loguru import logger

from app.agent.ask_user import NOBODY_TO_ASK
from app.agent.backend_client import backend_client
from app.agent.graph.services.citations import (
    CITATION_RULE,
    OUTPUT_FORMAT,
    assistant_rules,
    cited_ids,
    parse_answer,
    partial_answer,
    resolve_passages,
    without_invented_markers,
)
from app.agent.graph.services.events import emit, is_cancelled, set_activity
from app.agent.graph.services.memory import MEMORY_RULE, memory_block
from app.agent.graph.services.prompts import get_prompt
from app.agent.graph.services.vdb_router import collection_path, collection_path_names
from app.agent.graph.state import AgentState

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

# Added to the rules of the answer when the message carries images (#512): they are a source like the excerpts, and the
# one a claim drawn from them cannot cite - it needs no citation.
IMAGE_RULE = (
    "\n\nImages: the user attached image(s) to this message (or to the previous one, which this message may follow "
    "up). "
    "Look at them: they are part of what you answer from, together with the evidence excerpts when there are any. What "
    "an image shows needs no citation - cite the excerpts only for what comes from them - and when there are no "
    "excerpts, answer from the images alone. If an image does not show what is asked, say so plainly. Never claim to "
    "see what is not in an image."
)
# What the model wrote is handed to the chat in pieces at most this far apart: close enough to read as it is written,
# and far enough that a long answer is some hundreds of entries rather than one per token.
_DELTA_PUBLISH_INTERVAL_SECONDS = 0.05


async def _publish_delta(run_id: str, raw: str, shown: str) -> str:
    """Hands the chat what the model has written since the last time, and returns the answer as the chat has it now.

    The model writes JSON, of which the chat shows the "answer" field: what is sent is the new end of that text. When
    the text so far is no longer a continuation of what was sent (what looked like the start of the answer turned out
    not to be), the chat is sent the whole of it to put in place of its own."""
    now = partial_answer(raw)
    if now == shown:
        return shown
    if now.startswith(shown):
        await backend_client.publish_answer_delta(run_id, now[len(shown) :], replace=False)
    else:
        await backend_client.publish_answer_delta(run_id, now, replace=True)
    return now


async def _write_answer(run_id: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Has the model write the answer, publishing the text written so far (at most every
    _PARTIAL_PUBLISH_INTERVAL_SECONDS) so the chat shows it while it is still coming. Same result as
    llm_chat_with_usage. A stream that fails before anything was written falls back to the plain call,
    so streaming can never be the reason an answer is lost."""
    text = ""
    prompt_tokens = completion_tokens = None
    last_published = last_delta = 0.0
    shown = ""  # the answer as the chat has it so far
    try:
        await backend_client.set_partial_answer(run_id, "")
        async for item in backend_client.llm_chat_stream(model, messages):
            if item.get("done"):
                prompt_tokens, completion_tokens = item.get("prompt_tokens"), item.get("completion_tokens")
                continue
            text += item.get("delta", "")
            now = time.monotonic()
            if now - last_delta >= _DELTA_PUBLISH_INTERVAL_SECONDS:
                shown = await _publish_delta(run_id, text, shown)
                last_delta = now
            if now - last_published >= _PARTIAL_PUBLISH_INTERVAL_SECONDS:
                await backend_client.set_partial_answer(run_id, partial_answer(text))
                last_published = now
        await _publish_delta(run_id, text, shown)
    except Exception:
        if text:
            raise
        logger.exception("Streaming the answer failed, asking for it in one piece instead")
        return await backend_client.llm_chat_with_usage(model, messages)
    return {"content": text, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}


async def generate_answer(state: AgentState) -> dict[str, Any]:
    """Final answer generation (§22). Grounding in the given evidence is enforced structurally,
    not just requested: no excerpts means no citations means an explicit "couldn't find" answer,
    never a call to the model asked to answer anyway."""
    run_id = state["run_id"]
    if await is_cancelled(run_id):
        return {"cancelled": True}

    await set_activity(run_id, "generate_answer", "Generating the answer")
    await emit(run_id, "answer_generation_started")
    context = state["answer_context"]
    model = state["chat_model"]

    if model is None:
        return {
            "answer": "No language model is available to answer this query right now.",
            "citations": [],
        }

    # The images of the message (#512): read by the model that writes the answer - the one chosen if it reads images,
    # otherwise the hub's first that does, said in the run's events - and by no other call of the run.
    image_parts: list[dict[str, Any]] = []
    if state.get("images"):
        model, image_parts, unreadable = await _read_images(state, model)
        if unreadable is not None:
            return {"answer": unreadable, "citations": []}

    # Only worth suggesting when the run never had the option in the first place - if web search
    # was already on and still came up short, there's nothing left to point the user toward.
    web_search_hint = (
        " You could try enabling web search to look this up on the internet." if not state["web_search_enabled"] else ""
    )

    unexplored = _unexplored_paths(state)
    # With images, the answer does not need excerpts: it is written from what they show (#512).
    if not context["excerpts"] and not image_parts:
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

    system_prompt, prompt_version_id = await get_prompt("generate_answer", fallback=_SYSTEM_PROMPT)
    # Appended here, not in the prompt (administrable, see get_prompt): an overridden prompt keeps the rule (#402).
    system_prompt += CITATION_RULE + OUTPUT_FORMAT + assistant_rules(state.get("assistant_instructions", ""))
    if image_parts:
        system_prompt += IMAGE_RULE
    # The person's memory, when they have one on: handed over as data below the evidence, never in the system prompt.
    memory_items = list((state.get("memory") or {}).get("items") or [])
    if memory_items:
        system_prompt += MEMORY_RULE
    evidence_block = (
        "\n\n".join(f"[{e['id']}] (source: {e['source'] or e['tool']})\n{e['content']}" for e in context["excerpts"])
        or "(no excerpt from the knowledge bases: answer from the attached image(s))"
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
        f"\n\n{evidence_block}{memory_block(memory_items)}"
    )
    start = time.monotonic()
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [{"type": "text", "text": user_content}, *image_parts] if image_parts else user_content,
        },
    ]
    result = await _write_answer(run_id, model, messages)
    if memory_items:
        await backend_client.memory_used(run_id, [str(item["id"]) for item in memory_items])
    prompt_tokens = result.get("prompt_tokens")
    completion_tokens = result.get("completion_tokens")
    valid_ids = {e["id"] for e in context["excerpts"]}
    written, sources = _read_answer(result["content"], valid_ids)
    if not _cited(written, sources, valid_ids) and not image_parts:
        # Evidence was given and the answer cites none of it (#402): it stands, and the interface says that it has no
        # source. Not asked again: a second call would cost as much as the first for an answer that often is the same.
        logger.warning(f"Run {run_id}: the answer cites no evidence")
    cited = _cited(written, sources, valid_ids)
    passages = resolve_passages(sources, context["excerpts"])
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
            # The assistant that was consulted for this excerpt (#531), when it was not the run's own search.
            "consulted_assistant": e.get("consulted_assistant"),
            "evidence_kind": e["evidence_kind"],
            "document_id": e["document_id"],
            "chunk_id": e["chunk_id"],
            # Whether the answer cites this excerpt or it was only consulted (#402): the interface shows the cited.
            "cited": e["id"] in cited,
            # The passage the citation rests on, as the excerpt has it (found by the id and the passage the model
            # named, never the model's own copy) and where it is in `content`; None when the model gave none or the
            # one it gave is not in the excerpt - the citation then stands without a passage.
            "quote": passage.text if (passage := passages.get(e["id"])) else None,
            "quote_start": passage.start if passage else None,
            "quote_end": passage.end if passage else None,
            # Where a cited question-answer pair comes from (#351): the document, page and passage to open.
            "qa_source": e.get("qa_source"),
            "page_number": e["page_number"],
            "url": e["url"],
            "query": e["query"],
            "content": e["content"],
        }
        for e in context["excerpts"]
    ]
    await emit(run_id, "answer_generation_completed", {"citation_count": len(citations)})
    return {
        "answer": answer,
        "citations": citations,
        "answer_latency_ms": latency_ms,
        "answer_prompt_tokens": prompt_tokens,
        "answer_completion_tokens": completion_tokens,
        "prompt_usages": [prompt_version_id] if prompt_version_id else [],
    }


async def _read_images(state: AgentState, model: str) -> tuple[str, list[dict[str, Any]], str | None]:
    """The parts of the message that carry the images, and the model that will read them (#512).

    The model chosen when it reads images; otherwise the hub's first that does, and the run's events say so - the
    answer is never written by another model without telling. With no model that reads images, or no image that can be
    had, the third item is the answer to give instead: said plainly, with no model call lost."""
    run_id = state["run_id"]
    vision = await backend_client.get_vision_models()
    if not vision:
        return (
            model,
            [],
            "Je ne peux pas lire les images jointes : aucun modèle capable de lire les images n'est disponible.",
        )
    parts: list[dict[str, Any]] = []
    for image in state["images"]:
        fetched = await backend_client.get_run_image(run_id, image["id"])
        if fetched is None:
            continue
        data, content_type = fetched
        encoded = base64.b64encode(data).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}})
    if not parts:
        return (
            model,
            [],
            "Je n'ai pas pu lire les images jointes : elles ne sont plus disponibles. Joignez-les de nouveau.",
        )
    if model not in vision:
        await emit(run_id, "answer_model_switched", {"from": model, "to": vision[0], "reason": "images"})
        model = vision[0]
    await emit(run_id, "image_reading_started", {"count": len(parts)})
    return model, parts, None


def _read_answer(raw: str, valid_ids: set[str]) -> tuple[str, list[dict[str, Any]]]:
    """The answer the model wrote and the sources it named, without the citations that point to nothing."""
    answer, sources = parse_answer(raw)
    return without_invented_markers(answer, valid_ids), [s for s in sources if s.get("id") in valid_ids]


def _cited(answer: str, sources: list[dict[str, Any]], valid_ids: set[str]) -> set[str]:
    """The excerpts an answer cites: those its markers point to, and those it lists among its sources."""
    return set(cited_ids(answer, valid_ids)) | {s["id"] for s in sources}


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
