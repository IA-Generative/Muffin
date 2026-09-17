import uuid
from collections.abc import Callable
from typing import Any

import pytest

import app.backend_client as backend_client_module
import app.graph.nodes.build_research_plan as build_research_plan_module
import app.graph.nodes.generate_answer as generate_answer_module
import app.graph.nodes.load_accessible_vdbs as load_accessible_vdbs_module
import app.graph.nodes.research_task as research_task_module
import app.graph.nodes.targeted_research as targeted_research_module
import app.graph.services.events as events_module
import app.graph.services.llm as llm_module
from app.graph.graph import build_graph


class FakeBackend:
    """Stand-in for the real backend_client (§34/§36 - the graph is tested against a fake HTTP
    boundary, never a real backend, since this iteration is LangGraph-only)."""

    def __init__(self, accessible_vdbs: list[dict[str, Any]], llm_router: Callable[[str], str]) -> None:
        self.accessible_vdbs = accessible_vdbs
        self.llm_router = llm_router
        self.cancel_requested = False
        self.events: list[tuple[str, str | None]] = []
        self.searched_collection_ids: list[list[str]] = []

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"cancel_requested": self.cancel_requested}

    def add_run_event(
        self, run_id: str, type_: str, data: dict[str, Any] | None = None, task_id: str | None = None
    ) -> None:
        self.events.append((type_, task_id))

    def update_run_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def update_run_state(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_run_result(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_run_error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def list_accessible_collections(self, user_id: str) -> list[dict[str, Any]]:
        return self.accessible_vdbs

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
            }
            for collection_id in collection_ids
        ]

    def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        return self.llm_router(messages[0]["content"])

    def get_default_chat_model(self) -> str | None:
        return "test-model"


_PATCHED_MODULES = (
    backend_client_module,
    events_module,
    llm_module,
    load_accessible_vdbs_module,
    research_task_module,
    targeted_research_module,
    build_research_plan_module,
    generate_answer_module,
)


@pytest.fixture
def make_run():
    """Builds a compiled graph + FakeBackend pair, patched into every module that holds its own
    `backend_client` reference (each does `from app.backend_client import backend_client`, so
    patching the module attribute in isolation is not enough)."""

    def _make(accessible_vdbs: list[dict[str, Any]], llm_router: Callable[[str], str]):
        fake = FakeBackend(accessible_vdbs, llm_router)
        for module in _PATCHED_MODULES:
            module.backend_client = fake
        graph = build_graph()
        return graph, fake

    return _make


def initial_state(query: str, user_id: str = "user-1") -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "user_id": user_id,
        "conversation_id": "conv-1",
        "original_query": query,
        "messages": [{"role": "user", "content": query}],
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
