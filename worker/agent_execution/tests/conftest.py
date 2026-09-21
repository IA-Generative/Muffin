import uuid
from collections.abc import Callable
from typing import Any

import pytest

import app.backend_client as backend_client_module
import app.graph.nodes.answer_identity as answer_identity_module
import app.graph.nodes.build_research_plan as build_research_plan_module
import app.graph.nodes.generate_answer as generate_answer_module
import app.graph.nodes.load_accessible_vdbs as load_accessible_vdbs_module
import app.graph.nodes.research_task as research_task_module
import app.graph.nodes.targeted_research as targeted_research_module
import app.graph.services.events as events_module
import app.graph.services.llm as llm_module
import app.graph.services.prompts as prompts_module
from app.graph.graph import build_graph


class FakeBackend:
    """Stand-in for the real backend_client (§34/§36 - the graph is tested against a fake HTTP
    boundary, never a real backend, since this iteration is LangGraph-only)."""

    def __init__(self, accessible_vdbs: list[dict[str, Any]], llm_router: Callable[[str], str]) -> None:
        self.accessible_vdbs = accessible_vdbs
        self.llm_router = llm_router
        self.cancel_requested = False
        self.events: list[tuple[str, str | None]] = []
        self.activities: list[tuple[str, str]] = []  # [(node, activity), ...]
        self.searched_collection_ids: list[list[str]] = []
        self.accessible_collections_groups_requested: list[list[str]] = []
        # Empty by default - tests exercising the search tool go straight to tier 3 (chunk
        # search) unless a test explicitly seeds a QA-cache hit for tier 1.
        self.qa_hits: list[dict[str, Any]] = []
        # Empty by default - tests exercising the search tool go straight to tier 3 (chunk
        # search) unless a test explicitly seeds a summary-cache hit for tier 2.
        self.summary_hits: list[dict[str, Any]] = []
        # {collection_id: [{"id":..., "name":..., "status":..., "summary":...}, ...]}
        self.documents_by_collection: dict[str, list[dict[str, Any]]] = {}
        # {collection_id: [{"id":..., "name":..., "storage_key":..., "format":..., "row_count":...,
        #                    "column_count":..., "columns":[...], "measures":[...],
        #                    "dimensions":[...], "text_columns":[...]}, ...]}
        self.tabular_documents_by_collection: dict[str, list[dict[str, Any]]] = {}
        # {(document_id, page_number): {"page_number":..., "content":..., "screenshot_url":...}}
        self.pages: dict[tuple[str, int], dict[str, Any]] = {}
        self.conversation_titles: dict[str, str] = {}
        self.run_results: list[dict[str, Any]] = []
        self.active_prompts: dict[str, dict[str, Any]] = {}
        self.recorded_prompt_usages: list[str] = []
        # Every [system, user] messages list passed to llm_chat/llm_chat_with_usage, in order -
        # the router callback only ever sees the system prompt, so tests that need to assert on
        # the user content (e.g. a hint injected into it) read it from here instead.
        self.llm_calls: list[list[dict[str, str]]] = []

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"cancel_requested": self.cancel_requested}

    def add_run_event(
        self,
        run_id: str,
        type_: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.events.append((type_, task_id))

    def update_run_status(
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        current_activity: str | None = None,
    ) -> None:
        if current_node is not None and current_activity is not None:
            self.activities.append((current_node, current_activity))

    def update_run_state(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_run_result(
        self,
        run_id: str,
        answer: str,
        citations: list[dict[str, Any]],
        grounding_valid: bool | None = None,
        grounding_unsupported_claims: list[str] | None = None,
        grounding_research_count: int | None = None,
    ) -> None:
        self.run_results.append(
            {
                "answer": answer,
                "citations": citations,
                "grounding_valid": grounding_valid,
                "grounding_unsupported_claims": grounding_unsupported_claims,
                "grounding_research_count": grounding_research_count,
            }
        )

    def set_run_error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_accessible_collections(self, user_id: str, groups: list[str] | None = None) -> list[dict[str, Any]]:
        self.accessible_collections_groups_requested.append(groups or [])
        return self.accessible_vdbs

    def search_qa(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        return self.qa_hits

    def search_summaries(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        return self.summary_hits

    def search(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        self.searched_collection_ids.append(collection_ids)
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

    def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        self.llm_calls.append(messages)
        return self.llm_router(messages[0]["content"])

    def llm_chat_with_usage(
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

    def get_default_chat_model(self) -> str | None:
        return "test-model"

    def list_collection_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        return self.documents_by_collection.get(collection_id, [])

    def list_tabular_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        return self.tabular_documents_by_collection.get(collection_id, [])

    def get_document_page(self, user_id: str, document_id: str, page_number: int) -> dict[str, Any]:
        return self.pages[(document_id, page_number)]

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        self.conversation_titles[conversation_id] = title

    def get_active_prompt(self, name: str) -> dict[str, Any] | None:
        """Empty by default - get_prompt() then falls back to each node's own hardcoded
        constant, same system prompt text existing tests already assert on via llm_router.
        Tests exercising prompt versioning itself seed `fake.active_prompts[name]`."""
        return self.active_prompts.get(name)

    def add_prompt_usages(self, run_id: str, prompt_version_ids: list[str]) -> None:
        self.recorded_prompt_usages.extend(prompt_version_ids)


class FakeSearxng:
    """Stand-in for the real searxng_client - same fake-HTTP-boundary reasoning as FakeBackend."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.results = results if results is not None else []
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.results[:limit]


_PATCHED_MODULES = (
    backend_client_module,
    events_module,
    llm_module,
    load_accessible_vdbs_module,
    research_task_module,
    targeted_research_module,
    build_research_plan_module,
    generate_answer_module,
    answer_identity_module,
    prompts_module,
)


@pytest.fixture
def make_run():
    """Builds a compiled graph + FakeBackend pair, patched into every module that holds its own
    `backend_client` reference (each does `from app.backend_client import backend_client`, so
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
        graph = build_graph()
        return graph, fake

    return _make


def initial_state(
    query: str,
    user_id: str = "user-1",
    pinned_vdb_ids: list[str] | None = None,
    user_groups: list[str] | None = None,
    web_search_enabled: bool = False,
) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "user_id": user_id,
        "user_groups": user_groups or [],
        "conversation_id": "conv-1",
        "original_query": query,
        "contextualized_query": query,
        "messages": [{"role": "user", "content": query}],
        "chat_model": "test-model",
        "pinned_vdb_ids": pinned_vdb_ids or [],
        "web_search_enabled": web_search_enabled,
        "accessible_vdbs": [],
        "query_analysis": {},
        "research_plan": {},
        "research_tasks": [],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "evidence": [],
        "deduped_evidence": [],
        "coverage_result": None,
        "plan_version": 0,
        "replan_count": 0,
        "answer_context": None,
        "answer": None,
        "citations": [],
        "grounding_result": None,
        "grounding_research_count": 0,
        "execution_status": "queued",
        "cancelled": False,
    }
