import app.graph.services.vdb_router as vdb_router_module
from app.graph.services.vdb_router import select_relevant_vdbs


class _FakeBackendClient:
    def __init__(self, hits: list[dict] | None = None, raises: bool = False) -> None:
        self.hits = hits if hits is not None else []
        self.raises = raises
        self.calls: list[list[str]] = []

    def search_collections(self, collection_ids: list[str], query: str, limit: int) -> list[dict]:
        self.calls.append(collection_ids)
        if self.raises:
            raise RuntimeError("Meilisearch unreachable")
        return self.hits


def _vdbs(n: int) -> list[dict]:
    return [{"id": f"c{i}", "name": f"Collection {i}", "description": f"desc {i}"} for i in range(n)]


def _patch(monkeypatch, backend, *, selected_ids: list[str] | None = None) -> list[list[dict]]:
    """Patches both collaborators select_relevant_vdbs reaches for: the vector pre-filter's
    backend_client, and json_chat's own LLM call - captures every catalogue json_chat was given,
    in order, so a test can assert on exactly which candidates reached the LLM."""
    monkeypatch.setattr(vdb_router_module, "backend_client", backend)
    catalogues: list[list[dict]] = []

    def fake_json_chat(model, system_prompt, user_content, *, fallback):
        catalogues.append(user_content)
        return selected_ids

    monkeypatch.setattr(vdb_router_module, "json_chat", fake_json_chat)
    return catalogues


def test_below_threshold_skips_the_vector_prefilter(monkeypatch):
    backend = _FakeBackendClient()
    catalogues = _patch(monkeypatch, backend, selected_ids=["c0"])

    result = select_relevant_vdbs("query", _vdbs(5), "model")

    assert backend.calls == []  # too few accessible collections to bother pre-filtering
    assert len(catalogues) == 1
    assert result == [_vdbs(5)[0]]


def test_above_threshold_narrows_the_catalogue_sent_to_the_llm(monkeypatch):
    vdbs = _vdbs(25)
    backend = _FakeBackendClient(hits=[{"collection_id": "c0", "score": 0.9}, {"collection_id": "c1", "score": 0.8}])
    catalogues = _patch(monkeypatch, backend, selected_ids=["c0"])

    select_relevant_vdbs("query", vdbs, "model")

    assert backend.calls == [[f"c{i}" for i in range(25)]]  # every accessible id offered as a candidate
    assert "c0" in catalogues[0]
    assert "c1" in catalogues[0]
    assert "c2" not in catalogues[0]  # not in the pre-filter's top-K, never reaches the LLM


def test_pinned_collection_dropped_by_prefilter_still_reaches_the_llm(monkeypatch):
    vdbs = _vdbs(25)
    backend = _FakeBackendClient(hits=[{"collection_id": "c0", "score": 0.9}])
    catalogues = _patch(monkeypatch, backend, selected_ids=["c0"])

    result = select_relevant_vdbs("query", vdbs, "model", pinned_ids=["c24"])

    assert "c24" in catalogues[0]  # pinned by the user - the prefilter never gets to exclude it
    assert any(v["id"] == "c24" for v in result)


def test_vector_prefilter_failure_falls_back_to_every_accessible_vdb(monkeypatch):
    vdbs = _vdbs(25)
    backend = _FakeBackendClient(raises=True)
    catalogues = _patch(monkeypatch, backend, selected_ids=["c0"])

    select_relevant_vdbs("query", vdbs, "model")

    assert all(f"'id': 'c{i}'" in catalogues[0] for i in range(25))  # every id, unfiltered


def test_no_model_returns_every_accessible_vdb_unfiltered(monkeypatch):
    backend = _FakeBackendClient()
    _patch(monkeypatch, backend)

    result = select_relevant_vdbs("query", _vdbs(3), None)

    assert result == _vdbs(3)
    assert backend.calls == []  # no LLM configured - the vector pre-filter would be pointless too
