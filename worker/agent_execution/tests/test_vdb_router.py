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
            raise RuntimeError("Qdrant unreachable")
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


# --- Flat routing over sub-collections (#233) ---


def _tree() -> list[dict]:
    """A > A1 > A1a, A > A2, plus a flat root B."""
    return [
        {"id": "A", "parent_id": None, "name": "A", "description": "a"},
        {"id": "A1", "parent_id": "A", "name": "A1", "description": "a1"},
        {"id": "A1a", "parent_id": "A1", "name": "A1a", "description": "a1a"},
        {"id": "A2", "parent_id": "A", "name": "A2", "description": "a2"},
        {"id": "B", "parent_id": None, "name": "B", "description": "b"},
    ]


def _scripted(monkeypatch, *replies, prefilter_hits: list[str] | None = None) -> list[str]:
    """json_chat answers each routing call in turn; returns every user_content it was given. The
    vector pre-filter keeps `prefilter_hits` when the set is large enough to use it."""
    hits = [{"collection_id": vdb_id, "score": 0.9} for vdb_id in prefilter_hits or []]
    monkeypatch.setattr(vdb_router_module, "backend_client", _FakeBackendClient(hits=hits))
    remaining = list(replies)
    seen: list[str] = []

    def fake_json_chat(model, system_prompt, user_content, *, fallback):
        seen.append(user_content)
        return remaining.pop(0) if remaining else fallback

    monkeypatch.setattr(vdb_router_module, "json_chat", fake_json_chat)
    return seen


def _ids(vdbs: list[dict]) -> list[str]:
    return [v["id"] for v in vdbs]


def _wide_tree(width: int) -> list[dict]:
    """Root R with `width` sub-collections, over the pre-filter threshold."""
    return [{"id": "R", "parent_id": None, "name": "R", "description": "r"}] + [
        {"id": f"R{i}", "parent_id": "R", "name": f"R{i}", "description": f"r{i}"} for i in range(width)
    ]


def test_a_flat_set_never_reports_anything_unexplored(monkeypatch):
    _scripted(monkeypatch, ["c0"])

    result = select_relevant_vdbs("query", _vdbs(5), "model")

    assert _ids(result.selected) == ["c0"]
    assert result.unexplored == []


def test_a_deep_sub_collection_is_found_directly_in_one_call(monkeypatch):
    seen = _scripted(monkeypatch, ["A1a"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A1a"]
    assert len(seen) == 1  # every level in the same catalogue, a single LLM call
    assert "'path': 'A › A1 › A1a'" in seen[0]
    assert "'path'" not in seen[0].split("'id': 'B'")[1].split("}")[0]  # top-level: no path


def test_sub_collections_shown_and_rejected_are_not_unexplored(monkeypatch):
    _scripted(monkeypatch, ["A"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A"]
    assert result.unexplored == []  # the LLM saw A1, A1a and A2 and left them out


def test_sub_collections_cut_by_the_prefilter_are_unexplored(monkeypatch):
    _scripted(monkeypatch, ["R", "R0"], prefilter_hits=["R", "R0", "R1"])

    result = select_relevant_vdbs("query", _wide_tree(25), "model")

    assert _ids(result.selected) == ["R", "R0"]
    assert _ids(result.unexplored) == ["R"]  # R2..R24 were never shown to the LLM


def test_picks_over_the_cap_report_their_nearest_selected_ancestor(monkeypatch):
    monkeypatch.setattr(vdb_router_module.settings, "MAX_ROUTED_COLLECTIONS", 2)
    _scripted(monkeypatch, ["A", "A2", "A1"])

    result = select_relevant_vdbs("query", _tree(), "model")

    assert _ids(result.selected) == ["A", "A1"]  # catalogue order
    assert _ids(result.unexplored) == ["A"]  # A2 was picked but over the cap


def test_resumes_over_the_sub_collections_of_the_frontier_only(monkeypatch):
    seen = _scripted(monkeypatch, ["A1a"])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["A"])

    assert _ids(result.selected) == ["A1a"]
    assert all(f"'id': '{vdb_id}'" in seen[0] for vdb_id in ("A1", "A1a", "A2"))
    assert "'id': 'B'" not in seen[0] and "'id': 'A'," not in seen[0]  # nor the frontier itself


def test_resuming_into_irrelevant_sub_collections_searches_the_frontier_again(monkeypatch):
    _scripted(monkeypatch, [], [])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["A"])

    assert _ids(result.selected) == ["A"]


def test_an_inaccessible_resume_point_is_ignored(monkeypatch):
    _scripted(monkeypatch, ["B"])

    result = select_relevant_vdbs("query", _tree(), "model", resume_from_ids=["not-accessible"])

    assert _ids(result.selected) == ["B"]


def test_a_sub_collection_shared_on_its_own_shows_no_unreadable_ancestor(monkeypatch):
    seen = _scripted(monkeypatch, ["A1a"])
    without_root = [v for v in _tree() if v["id"] != "A"]

    result = select_relevant_vdbs("query", without_root, "model")

    assert _ids(result.selected) == ["A1a"]
    assert "'path': 'A1 › A1a'" in seen[0]
    assert "A ›" not in seen[0]  # the unreadable parent is never named


def test_pinned_collections_are_always_kept(monkeypatch):
    _scripted(monkeypatch, ["B"])

    result = select_relevant_vdbs("query", _tree(), "model", pinned_ids=["A2"])

    assert _ids(result.selected) == ["B", "A2"]
