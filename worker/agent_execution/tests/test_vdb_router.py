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

    result = select_relevant_vdbs("query", _vdbs(5), "model").selected

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

    result = select_relevant_vdbs("query", vdbs, "model", pinned_ids=["c24"]).selected

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

    result = select_relevant_vdbs("query", _vdbs(3), None).selected

    assert result == _vdbs(3)
    assert backend.calls == []  # no LLM configured - the vector pre-filter would be pointless too


# --- Sub-collection descent (#219) ---


def _tree() -> list[dict]:
    """A > A1 > A1a, A > A2, plus a flat root B."""
    return [
        {"id": "A", "parent_id": None, "name": "A", "description": "a"},
        {"id": "A1", "parent_id": "A", "name": "A1", "description": "a1"},
        {"id": "A1a", "parent_id": "A1", "name": "A1a", "description": "a1a"},
        {"id": "A2", "parent_id": "A", "name": "A2", "description": "a2"},
        {"id": "B", "parent_id": None, "name": "B", "description": "b"},
    ]


def _scripted(monkeypatch, *replies: list[str]) -> list[str]:
    """json_chat answers each routing call in turn - the top level first, then one call per level
    of the descent. Returns every user_content it was given."""
    monkeypatch.setattr(vdb_router_module, "backend_client", _FakeBackendClient())
    remaining = list(replies)
    seen: list[str] = []

    def fake_json_chat(model, system_prompt, user_content, *, fallback):
        seen.append(user_content)
        return remaining.pop(0) if remaining else fallback

    monkeypatch.setattr(vdb_router_module, "json_chat", fake_json_chat)
    return seen


def _ids(vdbs: list[dict]) -> list[str]:
    return [v["id"] for v in vdbs]


def test_a_flat_set_never_reports_anything_unexplored(monkeypatch):
    _scripted(monkeypatch, ["c0"])

    result = select_relevant_vdbs("query", _vdbs(5), "model")

    assert _ids(result.selected) == ["c0"]
    assert result.unexplored == []


def test_descends_level_by_level_from_the_top_level_only(monkeypatch):
    seen = _scripted(monkeypatch, ["A"], ["A1"], ["A1a"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A", "A1", "A1a"]
    assert result.unexplored == []
    assert "'id': 'A1'" not in seen[0]  # the first catalogue only has top-level collections
    assert "A › A1" in seen[1]  # sub-collections are shown with their path


def test_choosing_no_sub_collection_stops_the_descent(monkeypatch):
    seen = _scripted(monkeypatch, ["A"], [])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A"]
    assert result.unexplored == []
    assert len(seen) == 2


def test_depth_budget_reports_where_it_stopped(monkeypatch):
    monkeypatch.setattr(vdb_router_module.settings, "MAX_COLLECTION_DESCENT_DEPTH", 1)
    _scripted(monkeypatch, ["A"], ["A1"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A", "A1"]
    assert _ids(result.unexplored) == ["A1"]  # A1 still has A1a below it


def test_collection_budget_reports_the_parents_of_what_it_dropped(monkeypatch):
    monkeypatch.setattr(vdb_router_module.settings, "MAX_ROUTED_COLLECTIONS", 2)
    _scripted(monkeypatch, ["A"], ["A1", "A2"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A", "A1"]
    # A still has A2 left over, and A1 has A1a below it the budget never reached.
    assert _ids(result.unexplored) == ["A", "A1"]


def test_resumes_below_the_previous_frontier(monkeypatch):
    seen = _scripted(monkeypatch, ["A1a"])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["A1"])

    assert _ids(result.selected) == ["A1a"]
    assert len(seen) == 1  # straight to A1's sub-collections, no top-level routing
    assert "'id': 'A1a'" in seen[0]


def test_resuming_into_irrelevant_sub_collections_searches_the_frontier_again(monkeypatch):
    _scripted(monkeypatch, [])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["A1"])

    assert _ids(result.selected) == ["A1"]


def test_an_inaccessible_resume_point_is_ignored(monkeypatch):
    _scripted(monkeypatch, ["B"])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["not-accessible"])

    assert _ids(result.selected) == ["B"]


def test_a_sub_collection_shared_on_its_own_counts_as_top_level(monkeypatch):
    seen = _scripted(monkeypatch, ["A1"], ["A1a"])
    without_root = [v for v in _tree() if v["id"] != "A"]

    result = select_relevant_vdbs("query", without_root, "model")

    assert "'id': 'A1'" in seen[0]
    assert _ids(result.selected) == ["A1", "A1a"]
    assert "A ›" not in seen[1]  # the unreadable parent is never named


def test_pinned_collections_are_kept_without_being_descended(monkeypatch):
    _scripted(monkeypatch, ["B"])

    result = select_relevant_vdbs("query", _tree(), "model", pinned_ids=["A2"])

    assert _ids(result.selected) == ["B", "A2"]
