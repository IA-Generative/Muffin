import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.agent.usage_context import current_usage
from app.config import WorkerSettings


class EditRequestRefused(Exception):
    """The backend declined to start (or follow) an edit of a living document - `message` is in
    French and fit to tell the user, `code` is the machine-readable reason when there is one
    (draft_exists, document_locked...)."""

    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _refusal(error: httpx.HTTPStatusError) -> EditRequestRefused:
    """What the backend's error body says, as an EditRequestRefused. Its 409s carry
    {"code", "message"} (or, for a locked document, who holds the lock); the rest is a plain string."""
    status = error.response.status_code
    try:
        detail = error.response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict):
        code = detail.get("code")
        if code == "document_locked":
            who = detail.get("locked_by_display") or "quelqu'un d'autre"
            return EditRequestRefused(status, code, f"Ce document est en cours de modification par {who}.")
        return EditRequestRefused(status, code, str(detail.get("message") or "La modification a été refusée."))
    if status == 403:
        return EditRequestRefused(status, None, "Vous n'avez pas le droit de modifier ce document.")
    if status == 404:
        return EditRequestRefused(status, None, "Ce document est introuvable.")
    return EditRequestRefused(status, None, f"La demande de modification a échoué ({status}).")


class BackendClient:
    """Talks to the backend's /api/internal/* routes - its own, in the same process (in memory, through the application
    itself) - authenticated with the shared WORKER_API_KEY instead of a Keycloak session."""

    def __init__(self) -> None:
        self._api_key = WorkerSettings().WORKER_API_KEY
        self._http: httpx.AsyncClient | None = None

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            from app.main import app  # imported late: the application imports the runner that imports this

            self._http = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://backend.internal",
                headers={"X-API-Key": self._api_key},
            )
        return self._http

    async def get_run(self, run_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/api/internal/runs/{run_id}")
        response.raise_for_status()
        return response.json()

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        current_activity: str | None = None,
    ) -> None:
        response = await self._client.patch(
            f"/api/internal/runs/{run_id}/status",
            json={
                "status": status,
                "current_node": current_node,
                "current_activity": current_activity,
            },
        )
        response.raise_for_status()

    async def update_run_state(
        self,
        run_id: str,
        research_plan: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
        pending_human_action: dict[str, Any] | None = None,
        plan_version: int | None = None,
        replan_count: int | None = None,
    ) -> None:
        response = await self._client.patch(
            f"/api/internal/runs/{run_id}/state",
            json={
                "research_plan": research_plan,
                "budget": budget,
                "pending_human_action": pending_human_action,
                "plan_version": plan_version,
                "replan_count": replan_count,
            },
        )
        response.raise_for_status()

    async def set_run_result(
        self,
        run_id: str,
        answer: str,
        citations: list[dict[str, Any]],
        grounding_valid: bool | None = None,
        grounding_unsupported_claims: list[str] | None = None,
        grounding_research_count: int | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        edit_proposal: dict[str, Any] | None = None,
        unexplored_collection_ids: list[str] | None = None,
        questions: list[dict[str, Any]] | None = None,
    ) -> None:
        response = await self._client.patch(
            f"/api/internal/runs/{run_id}/result",
            json={
                "answer": answer,
                "citations": citations,
                "grounding_valid": grounding_valid,
                "grounding_unsupported_claims": grounding_unsupported_claims,
                "grounding_research_count": grounding_research_count,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "edit_proposal": edit_proposal,
                "unexplored_collection_ids": unexplored_collection_ids,
                "questions": questions,
            },
        )
        response.raise_for_status()

    async def set_run_grounding(self, run_id: str, grounding_valid: bool, unsupported_claims: list[str]) -> None:
        """The verdict of the check made once the answer is out (see ground_check)."""
        response = await self._client.patch(
            f"/api/internal/runs/{run_id}/grounding",
            json={"grounding_valid": grounding_valid, "grounding_unsupported_claims": unsupported_claims},
        )
        response.raise_for_status()

    async def list_editable_documents(self, run_id: str) -> list[dict[str, Any]]:
        """The living documents the run's user may change - computed backend-side from the run's own
        snapshot (user, groups, administrator flag), never from anything this worker supplies."""
        response = await self._client.get(f"/api/internal/runs/{run_id}/editable-documents")
        response.raise_for_status()
        return response.json()

    async def list_editable_collections(self, run_id: str) -> list[dict[str, Any]]:
        """The collections the run's user may add a document to - computed backend-side from the run's
        own snapshot, like list_editable_documents."""
        response = await self._client.get(f"/api/internal/runs/{run_id}/editable-collections")
        response.raise_for_status()
        return response.json()

    async def create_edit_request(self, run_id: str, document_id: str, prompt: str) -> dict[str, Any]:
        """Delegates an edit to the editing agent: the backend creates the draft (and the document
        lock) and sends the job. Returns the draft's state; raises EditRequestRefused when it
        declines (not allowed, locked by someone, a proposal already pending...)."""
        try:
            response = await self._client.post(
                f"/api/internal/runs/{run_id}/edit-requests", json={"document_id": document_id, "prompt": prompt}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise _refusal(error) from error
        return response.json()

    async def get_edit_request(self, run_id: str, document_id: str) -> dict[str, Any]:
        """Where the delegated edit stands. Reading it also keeps the draft (and its lock) alive."""
        try:
            response = await self._client.get(f"/api/internal/runs/{run_id}/edit-requests/{document_id}")
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise _refusal(error) from error
        return response.json()

    async def set_run_error(self, run_id: str, error: str) -> None:
        response = await self._client.patch(f"/api/internal/runs/{run_id}/error", json={"error": error})
        response.raise_for_status()

    async def create_chart(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Stores a chart the SQL worker drew (#434). The backend keeps the PNG and serves it with the rights of the
        conversation; it answers the URL and the Markdown that shows it."""
        response = await self._client.post(f"/api/internal/runs/{run_id}/charts", json=body)
        response.raise_for_status()
        return response.json()

    async def add_run_event(
        self,
        run_id: str,
        type_: str,
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        response = await self._client.post(
            f"/api/internal/runs/{run_id}/events",
            json={"type": type_, "data": data, "task_id": task_id},
        )
        response.raise_for_status()

    async def list_accessible_collections(self, user_id: str, groups: list[str] | None = None) -> list[dict[str, Any]]:
        # groups: this user's Keycloak groups at run creation time (Run.user_groups) - without
        # it, a collection shared to a group the user belongs to (see CollectionRepository.
        # list_all_accessible) would be invisible to the agent's VDB routing.
        response = await self._client.get(
            f"/api/internal/users/{user_id}/accessible-collections",
            params={"groups": groups or []},
        )
        response.raise_for_status()
        return response.json()

    async def search(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        """`include_descendants`: also the sub-collections below the given ones - read access is inherited down the
        tree, so the whole subtree is as readable as the collections the user can read."""
        response = await self._client.post(
            "/api/internal/search",
            json={
                "collection_ids": collection_ids,
                "query": query,
                "limit": limit,
                "include_descendants": include_descendants,
            },
        )
        response.raise_for_status()
        return response.json()

    async def search_qa(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        response = await self._client.post(
            "/api/internal/qa-search",
            json={
                "collection_ids": collection_ids,
                "query": query,
                "limit": limit,
                "include_descendants": include_descendants,
            },
        )
        response.raise_for_status()
        return response.json()

    async def search_summaries(
        self, collection_ids: list[str], query: str, limit: int, include_descendants: bool = False
    ) -> list[dict[str, Any]]:
        response = await self._client.post(
            "/api/internal/summary-search",
            json={
                "collection_ids": collection_ids,
                "query": query,
                "limit": limit,
                "include_descendants": include_descendants,
            },
        )
        response.raise_for_status()
        return response.json()

    async def search_collections(self, collection_ids: list[str], query: str, limit: int) -> list[dict[str, Any]]:
        """Vector search over collection *descriptions* (§ VDB routing pre-filter, #124) -
        restricted to `collection_ids`, so the backend never returns a collection the caller
        didn't already establish the user can access."""
        response = await self._client.post(
            "/api/internal/collections/search",
            json={"collection_ids": collection_ids, "query": query, "limit": limit},
        )
        response.raise_for_status()
        return response.json()

    async def llm_chat(self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        response = await self._client.post(
            "/api/internal/llm/chat",
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "usage": current_usage()},
        )
        response.raise_for_status()
        return response.json()["content"]

    async def llm_chat_with_usage(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> dict[str, Any]:
        """Same as llm_chat but also returns token usage (prompt_tokens, completion_tokens).
        Used by generate_answer to record per-message token stats on the assistant message.
        """
        response = await self._client.post(
            "/api/internal/llm/chat",
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "usage": current_usage()},
        )
        response.raise_for_status()
        data = response.json()
        return {
            "content": data["content"],
            "prompt_tokens": data.get("prompt_tokens"),
            "completion_tokens": data.get("completion_tokens"),
        }

    async def llm_chat_stream(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Same call as llm_chat_with_usage, but yields what the model writes as it writes it:
        {"delta": "..."} items, then a last {"done": True, "prompt_tokens", "completion_tokens"}."""
        # Not through the route: a streamed response is only handed over once it is whole in process, and the chat
        # shows the answer as it is written. The lines are read from the very generator the route sends.
        from app.routers.internal_llm import open_chat_stream
        from app.schemas.internal_pipeline import LlmChatRequest

        request = LlmChatRequest.model_validate(
            {"model": model, "messages": messages, "max_tokens": max_tokens, "usage": current_usage()}
        )
        async for line in await open_chat_stream(request):
            if line.strip():
                yield json.loads(line)

    async def publish_answer_delta(self, run_id: str, text: str, replace: bool = False) -> None:
        """Hands the chat what the model just wrote, for it to show at once (#510): the live stream of the run, which
        this pod writes to directly - nothing to go through, it is the very process that serves the chat's request when
        there is only one, and Redis is what carries it to the others. Best effort, like the partial answer."""
        from app.services import run_stream

        await run_stream.publish(run_id, run_stream.DELTA, {"text": text, "replace": replace})

    async def set_partial_answer(self, run_id: str, text: str) -> None:
        """Publishes the part of the answer written so far, for the chat to show while it is still being
        written. Best effort: a missed update only means the text shows up a little later."""
        try:
            await self._client.put(
                f"/api/internal/runs/{run_id}/partial-answer", json={"text": text}
            ).raise_for_status()
        except httpx.HTTPError:
            pass

    async def get_default_chat_model(self) -> str | None:
        response = await self._client.get("/api/internal/llm/default-chat-model")
        response.raise_for_status()
        return response.json()["model"]

    async def get_vision_models(self) -> list[str]:
        """The hub's models that read images (#512), cached backend-side. Empty when they cannot be had."""
        try:
            response = await self._client.get("/api/internal/llm/vision-models")
            response.raise_for_status()
            return response.json()["models"]
        except httpx.HTTPError:
            return []

    async def get_run_image(self, run_id: str, image_id: str) -> tuple[bytes, str] | None:
        """The bytes of an image the answer reads, and its type. None when it cannot be had: the answer is then written
        without it, and says so."""
        try:
            response = await self._client.get(f"/api/internal/runs/{run_id}/images/{image_id}")
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "image/png")
        except httpx.HTTPError:
            return None

    async def list_collection_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(f"/api/internal/users/{user_id}/collections/{collection_id}/documents")
        response.raise_for_status()
        return response.json()

    async def list_tabular_documents(self, user_id: str, collection_id: str) -> list[dict[str, Any]]:
        """Lists tabular documents in a collection that the agent can query with DuckDB.
        Returns id/name/storage_key/format + the full tabular profile (columns, classification)
        so the SQL generator has the schema without an extra round-trip."""
        response = await self._client.get(
            f"/api/internal/users/{user_id}/collections/{collection_id}/tabular-documents"
        )
        response.raise_for_status()
        return response.json()

    async def get_document_page(self, user_id: str, document_id: str, page_number: int) -> dict[str, Any]:
        response = await self._client.get(f"/api/internal/users/{user_id}/documents/{document_id}/pages/{page_number}")
        response.raise_for_status()
        return response.json()

    async def update_conversation_title(self, conversation_id: str, title: str) -> None:
        response = await self._client.patch(
            f"/api/internal/conversations/{conversation_id}/title",
            json={"title": title},
        )
        response.raise_for_status()

    async def check_guardrails(self, run_id: str) -> dict[str, Any]:
        """What the guardrails on the input decide for the request of this run (#516): `outcome` (`continue`,
        `continue_with_redaction`, `continue_with_warning`, `block`), the request as the models may read it, and the
        words for the person. Not caught: a check that cannot be made is not a check that passed - the run fails."""
        response = await self._client.post(f"/api/internal/runs/{run_id}/guardrails")
        response.raise_for_status()
        return response.json()

    async def tool_definitions(self, run_id: str) -> list[dict[str, Any]]:
        """The tools the person of this run may use now, as the model is given them. Empty when they cannot be
        had: a run goes on without tools rather than fail on them (#343)."""
        try:
            response = await self._client.post("/api/internal/tools/definitions", json={"run_id": run_id})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return []

    async def call_tool(self, run_id: str, ref: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One call of a tool for the person of this run. Always a result with a stable `code`, never an error of
        the tool; only the backend being unreachable is told as such."""
        try:
            response = await self._client.post(
                "/api/internal/tools/call", json={"run_id": run_id, "ref": ref, "arguments": arguments}
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return {"ok": False, "code": "erreur_outil", "text": "L'outil n'a pas pu être appelé.", "tool_name": ""}

    async def get_active_prompt(self, name: str) -> dict[str, Any] | None:
        """None on a 404 (no active version yet for this name) as well as any other failure -
        callers fall back to their own hardcoded default rather than crash the run over the
        prompt-versioning service being unavailable."""
        try:
            response = await self._client.get(f"/api/internal/prompts/{name}/active")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return None

    async def add_prompt_usages(self, run_id: str, prompt_version_ids: list[str]) -> None:
        response = await self._client.post(
            f"/api/internal/prompts/runs/{run_id}/usages",
            json={"prompt_version_ids": prompt_version_ids},
        )
        response.raise_for_status()

    async def add_task_logs(self, lines: list[dict]) -> None:
        """A short timeout: the lines are sent again with the next batch, a task never waits on them."""
        response = await self._client.post("/api/internal/task-logs", json={"entries": lines}, timeout=5.0)
        response.raise_for_status()

    async def add_execution_metric(self, metric: dict) -> None:
        """A short timeout: it is sent from a thread of its own and dropped if it fails, a task never waits on it."""
        response = await self._client.post("/api/internal/execution-metrics", json=metric, timeout=5.0)
        response.raise_for_status()


backend_client = BackendClient()
