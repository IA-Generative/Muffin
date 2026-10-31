import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

import app.agent.backend_client as backend_client_module
import app.agent.execution_metrics as execution_metrics_module
import app.agent.graph.nodes.answer_help as answer_help_module
import app.agent.graph.nodes.create as create_module
import app.agent.graph.nodes.edit as edit_module
import app.agent.graph.nodes.generate_answer as generate_answer_module
import app.agent.graph.nodes.ground_check as ground_check_module
import app.agent.graph.nodes.prepare as prepare_module
import app.agent.graph.nodes.research_task as research_task_module
import app.agent.graph.services.events as events_module
import app.agent.graph.services.llm as llm_module
import app.agent.graph.services.prompts as prompts_module
import app.agent.graph.services.tabular_query as tabular_query_module
import app.agent.graph.services.vdb_router as vdb_router_module
from app.agent.graph.graph import build_graph


async def _drop(_metric) -> None:
    return None


@pytest.fixture(autouse=True)
def _no_execution_metrics_sent(monkeypatch) -> None:
    """The steps of the graphs the tests run report what they cost, to a thread that sends them in the
    background: nothing of it may reach a backend, nor linger in that thread's queue for a later test."""
    monkeypatch.setattr(execution_metrics_module.backend_client, "add_execution_metric", _drop)


class FakeBackend:
    """Stand-in for the real backend_client (§34/§36 - the graph is tested against a fake HTTP
    boundary, never a real backend, since this iteration is LangGraph-only)."""

    def __init__(self, accessible_vdbs: list[dict[str, Any]], llm_router: Callable[[str], str]) -> None:
        self.accessible_vdbs = accessible_vdbs
        self.llm_router = llm_router
        self.cancel_requested = False
        self.events: list[tuple[str, str | None]] = []
        # The same events with their payload, in order.
        self.event_data: list[tuple[str, dict[str, Any] | None]] = []
        self.activities: list[tuple[str, str]] = []  # [(node, activity), ...]
        self.searched_collection_ids: list[list[str]] = []
        self.searched_with_descendants: list[bool] = []
        # [] by default - routing confidence is then "unknown" and routing goes on as it always did,
        # unless a test seeds the probe's hits ({"collection_id", "rank"}) to make it clear or flat.
        self.accessible_collections_groups_requested: list[list[str]] = []
        # [] by default - the vector pre-filter (§124) then falls back to every accessible VDB,
        # same as today's behaviour, unless a test seeds a scored subset here.
        self.collection_search_hits: list[dict[str, Any]] = []
        self.collection_search_calls: list[list[str]] = []
        # Empty by default - tests exercising the search tool go straight to tier 3 (chunk
        # search) unless a test explicitly seeds a QA-cache hit for tier 1.
        self.qa_hits: list[dict[str, Any]] = []
        # Empty by default - tests exercising the search tool go straight to tier 3 (chunk
        # search) unless a test explicitly seeds a summary-cache hit for tier 2.
        self.summary_hits: list[dict[str, Any]] = []
        # {collection_id: [{"id":..., "name":..., "status":..., "summary":...}, ...]}
        self.documents_by_collection: dict[str, list[dict[str, Any]]] = {}
        # {collection_id: [{"id":..., "name":..., "format":..., "row_count":...,
        #                    "column_count":..., "columns":[...], "measures":[...], "sheets":[{index,name,rows,
        #                    "dimensions":[...], "text_columns":[...]}, ...]}
        self.tabular_documents_by_collection: dict[str, list[dict[str, Any]]] = {}
        # Every chart the agent asked the backend to keep (#434): (run_id, body).
        self.charts: list[tuple[str, dict[str, Any]]] = []
        # {(document_id, page_number): {"page_number":..., "content":..., "screenshot_url":...}}
        self.pages: dict[tuple[str, int], dict[str, Any]] = {}
        self.conversation_titles: dict[str, str] = {}
        self.run_results: list[dict[str, Any]] = []
        self.groundings: list[tuple[str, bool, list[str]]] = []
        self.active_prompts: dict[str, dict[str, Any]] = {}
        self.recorded_prompt_usages: list[str] = []
        # Every [system, user] messages list passed to llm_chat/llm_chat_with_usage, in order -
        # the router callback only ever sees the system prompt, so tests that need to assert on
        # the user content (e.g. a hint injected into it) read it from here instead.
        self.llm_calls: list[list[dict[str, str]]] = []
        # What the streamed answer published while it was being written, and a failure to simulate.
        self.partial_answers: list[str] = []
        self.stream_error: Exception | None = None
        # Delegating an edit of a living document (#171): what the backend says the user may edit,
        # the states the draft goes through (the first answers create_edit_request, each later one a
        # poll, the last repeats), and what the agent asked for.
        self.editable_documents: list[dict[str, Any]] = []
        self.editable_calls: list[str] = []
        self.edit_states: list[dict[str, Any]] = []
        self.edit_creates: list[tuple[str, str, str]] = []
        self.edit_polls = 0
        # Creating a Markdown document on request: the collections the user may add one to.
        self.editable_collections: list[dict[str, Any]] = []
        self.editable_collections_calls: list[str] = []
        self.edit_refusal: Exception | None = None
        self.edit_gone: Exception | None = None

    async def list_editable_documents(self, run_id: str) -> list[dict[str, Any]]:
        self.editable_calls.append(run_id)
        return self.editable_documents

    async def list_editable_collections(self, run_id: str) -> list[dict[str, Any]]:
        self.editable_collections_calls.append(run_id)
        return self.editable_collections

    async def create_edit_request(self, run_id: str, document_id: str, prompt: str) -> dict[str, Any]:
        self.edit_creates.append((run_id, document_id, prompt))
        if self.edit_refusal is not None:
            raise self.edit_refusal
        return self.edit_states[0]

    async def get_edit_request(self, run_id: str, document_id: str) -> dict[str, Any]:
        self.edit_polls += 1
        if self.edit_gone is not None:
            raise self.edit_gone
        return self.edit_states[min(self.edit_polls, len(self.edit_states) - 1)]

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return {"cancel_requested": self.cancel_requested}

    async def add_run_event(
        self,
        run_id: str,
        type_: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.events.append((type_, task_id))
        self.event_data.append((type_, data))

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        current_activity: str | None = None,
    ) -> None:
        if current_node is not None and current_activity is not None:
            self.activities.append((current_node, current_activity))

    async def update_run_state(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def set_run_result(
        self,
        run_id: str,
        answer: str,
        citations: list[dict[str, Any]],
        grounding_valid: bool | None = None,
        grounding_unsupported_claims: list[str] | None = None,
        grounding_research_count: int | None = None,
        edit_proposal: dict[str, Any] | None = None,
    ) -> None:
        self.run_results.append(
            {
                "answer": answer,
                "citations": citations,
                "edit_proposal": edit_proposal,
                "grounding_valid": grounding_valid,
                "grounding_unsupported_claims": grounding_unsupported_claims,
                "grounding_research_count": grounding_research_count,
            }
        )

    async def set_run_error(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def set_run_grounding(self, run_id: str, grounding_valid: bool, unsupported_claims: list[str]) -> None:
        self.groundings.append((run_id, grounding_valid, unsupported_claims))

    async def list_accessible_collections(self, user_id: str, groups: list[str] | None = None) -> list[dict[str, Any]]:
        self.accessible_collections_groups_requested.append(groups or [])
        return self.accessible_vdbs

    async def search_qa(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        return self.qa_hits

    async def search_summaries(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        return self.summary_hits

    async def search_collections(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        self.collection_search_calls.append(collection_ids)
        return self.collection_search_hits

    async def search(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        self.searched_collection_ids.append(collection_ids)
        self.searched_with_descendants.append(include_descendants)
        return [
            {
                "chunk_id": str(uuid.uuid4()),
                "document_id": str(uuid.uuid4()),
                "document_name": "doc.pdf",
                "collection_id": collection_id,
                "text": f"evidence about '{query}' from {collection_id}",
                "rank": 0.5,
                "page_number": 3,
            }
            for collection_id in collection_ids
        ]

    async def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        self.llm_calls.append(messages)
        return self.llm_router(messages[0]["content"])

    async def llm_chat_with_usage(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> dict[str, Any]:
        """Same contract as the real backend_client: returns content + token usage.
        The content comes from the llm_router (keyed on the system prompt), and token
        counts are stubbed since tests don't assert on them."""
        self.llm_calls.append(messages)
        content = self.llm_router(messages[0]["content"])
        return {
            "content": content,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

    async def get_default_chat_model(self) -> str | None:
        return "test-model"

    async def list_collection_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        return self.documents_by_collection.get(collection_id, [])

    async def create_chart(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.charts.append((run_id, body))
        url = f"/api/conversations/conv-1/charts/chart-{len(self.charts)}.png"
        return {
            "id": f"chart-{len(self.charts)}",
            "title": body["title"],
            "url": url,
            "markdown": f"![{body['title']}]({url})",
        }

    async def list_tabular_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        return self.tabular_documents_by_collection.get(collection_id, [])

    async def get_document_page(self, user_id: str, document_id: str, page_number: int) -> dict[str, Any]:
        return self.pages[(document_id, page_number)]

    async def update_conversation_title(self, conversation_id: str, title: str) -> None:
        self.conversation_titles[conversation_id] = title

    async def get_active_prompt(self, name: str) -> dict[str, Any] | None:
        """Empty by default - get_prompt() then falls back to each node's own hardcoded
        constant, same system prompt text existing tests already assert on via llm_router.
        Tests exercising prompt versioning itself seed `fake.active_prompts[name]`."""
        return self.active_prompts.get(name)

    async def add_prompt_usages(self, run_id: str, prompt_version_ids: list[str]) -> None:
        self.recorded_prompt_usages.extend(prompt_version_ids)

    async def llm_chat_stream(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Same contract as the real backend_client: the router's content in two deltas, then the usage."""
        if self.stream_error is not None:
            raise self.stream_error
        self.llm_calls.append(messages)
        content = self.llm_router(messages[0]["content"])
        half = len(content) // 2
        yield {"delta": content[:half]}
        yield {"delta": content[half:]}
        yield {"done": True, "prompt_tokens": 100, "completion_tokens": 50}

    async def set_partial_answer(self, run_id: str, text: str) -> None:
        self.partial_answers.append(text)


class FakeSearxng:
    """Stand-in for the real searxng_client - same fake-HTTP-boundary reasoning as FakeBackend."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.results = results if results is not None else []
        self.queries: list[str] = []

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.results[:limit]


_PATCHED_MODULES = (
    backend_client_module,
    events_module,
    llm_module,
    prepare_module,
    edit_module,
    create_module,
    research_task_module,
    generate_answer_module,
    ground_check_module,
    answer_help_module,
    prompts_module,
    vdb_router_module,
    tabular_query_module,
)


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def make_run():
    """Builds a compiled graph + FakeBackend pair, patched into every module that holds its own
    `backend_client` reference (each does `from app.agent.backend_client import backend_client`, so
    patching the module attribute in isolation is not enough)."""

    def _make(
        accessible_vdbs: list[dict[str, Any]],
        llm_router: Callable[[str], str],
        web_results: list[dict[str, Any]] | None = None,
    ):
        fake = FakeBackend(accessible_vdbs, llm_router)
        for module in _PATCHED_MODULES:
            module.backend_client = fake
        # get_prompt() caches by name across calls (see prompts.py) - stale across tests
        # otherwise, since the module-level cache dict outlives any single fake backend.
        prompts_module._cache.clear()
        # Attached to `fake` (not a 3rd return value) so every existing `graph, fake =
        # make_run(...)` call site keeps working unchanged - only tests that care about web
        # search reach for `fake.searxng`.
        fake.searxng = FakeSearxng(web_results)
        research_task_module.searxng_client = fake.searxng
        # The wait for the editing agent polls the backend on a timer - tests don't really sleep.
        edit_module._sleep = _no_sleep
        graph = build_graph()
        return graph, fake

    return _make


def initial_state(
    query: str,
    user_id: str = "user-1",
    pinned_vdb_ids: list[str] | None = None,
    user_groups: list[str] | None = None,
    web_search_enabled: bool = False,
    resume_from_vdb_ids: list[str] | None = None,
    interactive: bool = True,
    question_rounds: int = 0,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "user_id": user_id,
        "user_groups": user_groups or [],
        "conversation_id": "conv-1",
        "original_query": query,
        "contextualized_query": query,
        "messages": [*(history or []), {"role": "user", "content": query}],
        "chat_model": "test-model",
        "pinned_vdb_ids": pinned_vdb_ids or [],
        "web_search_enabled": web_search_enabled,
        "resume_from_vdb_ids": resume_from_vdb_ids or [],
        "unexplored_vdb_ids": [],
        "interactive": interactive,
        "question_rounds": question_rounds,
        "questions": None,
        "must_assume": False,
        "accessible_vdbs": [],
        "catalogue": [],
        "edit_candidates": [],
        "create_candidates": [],
        "plan": {},
        "scope_ids": [],
        "widened": False,
        "edit_target": None,
        "edit_proposal": None,
        "create_target": None,
        "query_analysis": {},
        "research_tasks": [],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "evidence": [],
        "deduped_evidence": [],
        "coverage_result": None,
        "answer_context": None,
        "answer": None,
        "citations": [],
        "needs_grounding": False,
        "grounding_result": None,
        "prompt_usages": [],
        "execution_status": "queued",
        "cancelled": False,
    }
