"""The Qdrant-backed vector store: hybrid search (dense + BM25 fused by RRF), batched reads and writes, and the
blue/green rebuild by alias (#12, #355). Runs against an in-memory Qdrant, and against a real server too when
one answers at QDRANT_TEST_URL (CI starts one)."""

import os
import threading
import uuid
from unittest.mock import patch

import pytest
from qdrant_client import QdrantClient

from app.services import vector_store

SERVER_URL = os.environ.get("QDRANT_TEST_URL", "http://localhost:56333")


def _server_client() -> QdrantClient | None:
    try:
        client = QdrantClient(url=SERVER_URL, check_compatibility=False, timeout=3)
        client.get_collections()
        return client
    except Exception:
        return None


@pytest.fixture(params=["memory", "server"])
def qdrant(request, monkeypatch):
    if request.param == "memory":
        client = QdrantClient(":memory:")
    else:
        client = _server_client()
        if client is None:
            # Set explicitly (CI), a server that is down is a failure, not a reason to skip.
            if "QDRANT_TEST_URL" in os.environ:
                pytest.fail(f"no Qdrant server at {SERVER_URL}")
            pytest.skip(f"no Qdrant server at {SERVER_URL}")
        client.delete_collection(vector_store._COLLECTIONS)
    monkeypatch.setattr(vector_store, "_client", client)
    return client


@pytest.fixture
def collection(qdrant):
    collection_id = uuid.uuid4()
    yield collection_id
    vector_store.delete_collection(collection_id)


def _chunk(collection_id, embedding, text):
    point_id = uuid.uuid4()
    vector_store.upsert_chunk_embedding(collection_id, point_id, embedding, text, "model-a")
    return point_id


# -- hybrid search ----------------------------------------------------------------------------------


def test_a_point_only_the_lexical_branch_finds_is_returned(collection):
    """A case number or a proper name: its embedding says nothing close to the query's, its text does."""
    code = _chunk(collection, [0, 1, 0], "Dossier AB-1234 de la commune")
    _chunk(collection, [0, 0, 1], "Un texte sans rapport")

    hits = vector_store.search(collection, "AB-1234", [1, 0, 0], limit=5)

    assert code in [point_id for point_id, _ in hits]
    ranks = vector_store.explain_search(collection, "AB-1234", [1, 0, 0])
    assert code in ranks["sparse"]


def test_the_score_of_a_hit_is_the_cosine_of_its_dense_vector_even_when_only_lexical_found_it(collection):
    code = _chunk(collection, [0, 1, 0], "Dossier AB-1234")
    close = _chunk(collection, [1, 0.1, 0], "Rien en commun")

    scores = dict(vector_store.search(collection, "AB-1234", [1, 0, 0], limit=5))

    assert scores[code] == pytest.approx(0.0)
    assert scores[close] == pytest.approx(1 / (1 + 0.1**2) ** 0.5)


def test_a_paraphrase_is_found_by_the_dense_branch_alone(collection):
    paraphrase = _chunk(collection, [1, 0, 0], "La voiture roule vite")
    _chunk(collection, [0, 1, 0], "Autre sujet")

    hits = vector_store.search(collection, "automobile rapide", [1, 0, 0], limit=5)

    assert hits[0][0] == paraphrase
    assert paraphrase not in vector_store.explain_search(collection, "automobile rapide", [1, 0, 0])["sparse"]


def test_a_point_found_by_both_branches_comes_before_one_found_by_a_single_branch(collection):
    both = _chunk(collection, [1, 0, 0], "tarif du stationnement")
    dense_only = _chunk(collection, [0.9, 0.3, 0], "autre texte")
    lexical_only = _chunk(collection, [0, 0, 1], "stationnement")

    ids = [point_id for point_id, _ in vector_store.search(collection, "tarif du stationnement", [1, 0, 0], limit=5)]

    assert ids[0] == both
    assert set(ids) == {both, dense_only, lexical_only}


def test_the_rrf_order_follows_the_ranks_in_each_branch(collection):
    """Ranked 1st by one branch and last by the other, a point loses to one that is 2nd in both."""
    steady = _chunk(collection, [0.9, 0.4, 0], "stationnement payant centre ville")
    dense_best = _chunk(collection, [1, 0, 0], "sans rapport")
    lexical_best = _chunk(collection, [0, 0, 1], "stationnement payant")

    ids = [point_id for point_id, _ in vector_store.search(collection, "stationnement payant", [1, 0, 0], limit=5)]

    assert ids.index(steady) < max(ids.index(dense_best), ids.index(lexical_best))
    ranks = vector_store.explain_search(collection, "stationnement payant", [1, 0, 0])
    assert ranks["dense"][dense_best] == 1 and ranks["sparse"][lexical_best] <= 2


def test_accents_case_and_inflections_do_not_prevent_a_lexical_match(collection):
    point = _chunk(collection, [0, 1, 0], "Les Écoles maternelles de la commune")

    assert point in vector_store.explain_search(collection, "ecole MATERNELLE", [1, 0, 0])["sparse"]


def test_a_typo_is_not_tolerated_by_the_lexical_branch(collection):
    """What a typo-tolerant engine would forgive: BM25 matches terms, not nearly-terms (documented in the settings)."""
    point = _chunk(collection, [0, 1, 0], "Règlement du stationnement")

    assert point not in vector_store.explain_search(collection, "stationnemet", [1, 0, 0])["sparse"]


def test_a_search_only_returns_the_asked_kind(collection):
    chunk = _chunk(collection, [1, 0, 0], "texte commun")
    qa, summary = uuid.uuid4(), uuid.uuid4()
    vector_store.upsert_qa_embedding(collection, qa, [1, 0, 0], "texte commun", "model-a")
    vector_store.upsert_summary_embedding(collection, summary, [1, 0, 0], "texte commun", "model-a")

    assert [p for p, _ in vector_store.search(collection, "texte commun", [1, 0, 0], 10)] == [chunk]
    assert [p for p, _ in vector_store.search_qa(collection, "texte commun", [1, 0, 0], 10)] == [qa]
    assert [p for p, _ in vector_store.search_summaries(collection, "texte commun", [1, 0, 0], 10)] == [summary]


def test_a_query_of_stop_words_only_falls_back_on_the_dense_branch(collection):
    point = _chunk(collection, [1, 0, 0], "quelque chose")

    assert vector_store.search(collection, "le la les", [1, 0, 0], limit=3)[0][0] == point


def test_searching_a_collection_nothing_was_indexed_in_returns_nothing(collection):
    assert vector_store.search(collection, "texte", [1, 0, 0], limit=3) == []


def test_idf_makes_a_rare_term_weigh_more_than_a_frequent_one(collection):
    for index in range(8):
        _chunk(collection, [0, 0, 1], f"contrat numéro {index}")
    rare = _chunk(collection, [0, 1, 0], "avenant exceptionnel")

    ranks = vector_store.explain_search(collection, "contrat avenant", [1, 0, 0])

    assert ranks["sparse"][rare] == 1


def test_each_branch_is_logged_when_asked(collection, monkeypatch):
    _chunk(collection, [1, 0, 0], "texte commun")
    monkeypatch.setattr(vector_store._settings, "SEARCH_LOG_BRANCHES", True)
    messages = []

    with patch.object(vector_store.logger, "debug", side_effect=messages.append):
        vector_store.search(collection, "texte commun", [1, 0, 0], limit=3)

    assert len(messages) == 1 and "branch ranks={'dense': 1, 'sparse': 1}" in messages[0]


# -- collection descriptions ------------------------------------------------------------------------


def test_the_collection_search_never_leaves_the_given_candidates(qdrant):
    allowed, forbidden = uuid.uuid4(), uuid.uuid4()
    vector_store.upsert_collection_description(allowed, "Urbanisme et permis", ["plu"], [1, 0, 0])
    vector_store.upsert_collection_description(forbidden, "Urbanisme et permis", ["plu"], [1, 0, 0])
    try:
        hits = vector_store.search_collections("urbanisme", [1, 0, 0], [allowed], limit=5)

        assert [point_id for point_id, _ in hits] == [allowed]
        assert vector_store.search_collections("urbanisme", [1, 0, 0], [], limit=5) == []
    finally:
        vector_store.delete_collection(allowed)
        vector_store.delete_collection(forbidden)


def test_tags_are_searchable_text_and_can_change_without_the_embedding(qdrant):
    collection_id = uuid.uuid4()
    vector_store.upsert_collection_description(collection_id, "Documents divers", [], [0, 1, 0])
    try:
        assert vector_store.search_collections("budget", [1, 0, 0], [collection_id], 5)[0][1] == pytest.approx(0.0)
        before = vector_store._client.retrieve("collections", [str(collection_id)], with_vectors=True)[0].vector

        vector_store.update_collection_tags_in_index(collection_id, ["budget"])

        after = vector_store._client.retrieve("collections", [str(collection_id)], with_vectors=True)[0]
        assert after.payload["tags"] == ["budget"]
        assert after.vector["dense"] == before["dense"]
        assert after.vector["sparse"] != before["sparse"]
    finally:
        vector_store.delete_collection(collection_id)


def test_updating_the_tags_of_a_collection_never_described_does_nothing(qdrant):
    vector_store.update_collection_tags_in_index(uuid.uuid4(), ["x"])
    vector_store.upsert_collection_description(uuid.uuid4(), "d", [], [1, 0, 0])
    vector_store.update_collection_tags_in_index(uuid.uuid4(), ["x"])


# -- reading and deleting ---------------------------------------------------------------------------


def test_the_vectors_of_many_points_are_read_in_a_single_call(collection):
    ids = [_chunk(collection, [1, 0, index], f"texte {index}") for index in range(5)]

    with patch.object(vector_store._client, "retrieve", wraps=vector_store._client.retrieve) as retrieve:
        vectors = vector_store.read_vectors(collection, [*ids, uuid.uuid4()])

    assert retrieve.call_count == 1
    assert set(vectors) == set(ids)
    # Qdrant stores a cosine vector normalised: the same direction, which is all a copy needs.
    vector, model = vectors[ids[2]]
    assert vector == pytest.approx([1 / 5**0.5, 0.0, 2 / 5**0.5])
    assert model == "model-a"


def test_a_point_indexed_before_the_model_was_recorded_has_no_model(collection):
    point_id = uuid.uuid4()
    vector_store.upsert_chunk_embedding(collection, point_id, [0.5, 0.5], "t")

    vectors = vector_store.read_vectors(collection, [point_id])
    assert vectors[point_id][0] == pytest.approx([0.5**0.5, 0.5**0.5])
    assert vectors[point_id][1] is None
    assert vector_store.read_vectors(collection, []) == {}
    assert vector_store.read_vectors(uuid.uuid4(), [point_id]) == {}


def test_deleting_a_document_clears_its_chunks_and_summary_from_both_collections(collection):
    document_id, chunk = uuid.uuid4(), _chunk(collection, [1, 0], "texte")
    vector_store.upsert_summary_embedding(collection, document_id, [1, 0], "résumé", "model-a")
    vector_store.upsert_points(collection, [("chunk", chunk, "texte", [1, 0])], "model-b", next_index=True)
    kept = _chunk(collection, [1, 0], "autre")

    vector_store.delete_document_embeddings(collection, document_id, [chunk])

    assert set(vector_store.list_points(collection, next_index=False)) == {str(kept)}
    assert vector_store.list_points(collection, next_index=True) == {}


def test_deleting_a_collection_removes_the_alias_and_both_physical_collections(collection, qdrant):
    _chunk(collection, [1, 0], "texte")
    vector_store.upsert_points(collection, [("chunk", uuid.uuid4(), "t", [1, 0, 0])], "m", next_index=True)

    vector_store.delete_collection(collection)

    assert not qdrant.collection_exists(f"chunks_{collection}")
    assert not qdrant.collection_exists(f"chunks_{collection}_a")
    assert not qdrant.collection_exists(f"chunks_{collection}_b")


def test_deleting_what_does_not_exist_is_harmless(qdrant):
    vector_store.delete_collection(uuid.uuid4())
    vector_store.delete_chunk_embeddings(uuid.uuid4(), [uuid.uuid4()])


# -- blue/green rebuild -----------------------------------------------------------------------------


def test_points_are_listed_with_their_kind_text_and_model_across_pages(collection, monkeypatch):
    monkeypatch.setattr(vector_store, "_PAGE", 2)
    ids = [_chunk(collection, [1, 0], f"texte {index}") for index in range(5)]

    points = vector_store.list_points(collection, next_index=False)

    assert set(points) == {str(point_id) for point_id in ids}
    assert points[str(ids[1])] == {"kind": "chunk", "text": "texte 1", "model": "model-a"}
    assert vector_store.list_points(uuid.uuid4(), next_index=False) == {}


def test_the_rebuilt_index_is_invisible_until_the_swap_then_replaces_the_old_one(collection):
    old = _chunk(collection, [1, 0, 0], "ancien texte")
    new = uuid.uuid4()

    vector_store.upsert_points(
        collection, [("chunk", new, "nouveau texte", [1, 0, 0, 0, 0])], "model-b", next_index=True
    )

    assert vector_store.next_index_exists(collection)
    assert [p for p, _ in vector_store.search(collection, "texte", [1, 0, 0], 5)] == [old]

    vector_store.swap_with_next(collection)

    # Another dimension: the query is now embedded with the new model.
    assert [p for p, _ in vector_store.search(collection, "texte", [1, 0, 0, 0, 0], 5)] == [new]
    assert set(vector_store.list_points(collection, next_index=True)) == {str(old)}


def test_a_rollback_is_the_same_swap_again(collection):
    old = _chunk(collection, [1, 0, 0], "ancien texte")
    new = uuid.uuid4()
    vector_store.upsert_points(collection, [("chunk", new, "nouveau", [1, 0])], "model-b", next_index=True)
    vector_store.swap_with_next(collection)

    vector_store.swap_with_next(collection)

    assert [p for p, _ in vector_store.search(collection, "texte", [1, 0, 0], 5)] == [old]
    vector_store.delete_next_index(collection)
    assert not vector_store.next_index_exists(collection)


def test_a_collection_with_nothing_indexed_before_the_rebuild_gets_its_alias_on_the_swap(collection):
    point = uuid.uuid4()
    vector_store.upsert_points(collection, [("chunk", point, "texte", [1, 0])], "model-b", next_index=True)
    assert vector_store.search(collection, "texte", [1, 0], 5) == []

    vector_store.swap_with_next(collection)

    assert [p for p, _ in vector_store.search(collection, "texte", [1, 0], 5)] == [point]


def test_a_write_to_the_active_index_during_a_rebuild_of_an_unindexed_collection_keeps_the_rebuild(collection):
    rebuilt = uuid.uuid4()
    vector_store.upsert_points(collection, [("chunk", rebuilt, "texte", [1, 0])], "model-b", next_index=True)
    live = _chunk(collection, [1, 0], "ecrit pendant la reconstruction")

    assert set(vector_store.list_points(collection, next_index=True)) == {str(rebuilt)}
    assert set(vector_store.list_points(collection, next_index=False)) == {str(live)}
    vector_store.swap_with_next(collection)
    assert set(vector_store.list_points(collection, next_index=False)) == {str(rebuilt)}


def test_swapping_without_a_rebuilt_index_raises(collection):
    _chunk(collection, [1, 0], "texte")

    with pytest.raises(RuntimeError):
        vector_store.swap_with_next(collection)


def test_a_second_rebuild_after_a_finalized_one_reuses_the_freed_collection(collection):
    _chunk(collection, [1, 0, 0], "v1")
    vector_store.upsert_points(collection, [("chunk", uuid.uuid4(), "v2", [1, 0])], "m2", next_index=True)
    vector_store.swap_with_next(collection)
    vector_store.delete_next_index(collection)
    third = uuid.uuid4()

    vector_store.upsert_points(collection, [("chunk", third, "v3", [1, 0, 0, 0])], "m3", next_index=True)
    vector_store.swap_with_next(collection)

    assert [p for p, _ in vector_store.search(collection, "v3", [1, 0, 0, 0], 5)] == [third]


def test_deleting_points_by_id_targets_one_index(collection):
    kept, gone = _chunk(collection, [1, 0], "a"), _chunk(collection, [1, 0], "b")

    vector_store.delete_points(collection, [str(gone)], next_index=False)
    vector_store.delete_points(collection, [], next_index=False)

    assert set(vector_store.list_points(collection, next_index=False)) == {str(kept)}


def test_the_swap_is_atomic_for_searches_running_while_it_happens(request, collection):
    if "server" not in request.node.callspec.id:
        pytest.skip("atomicity is a property of the server")
    old = _chunk(collection, [1, 0, 0], "texte")
    new = uuid.uuid4()
    vector_store.upsert_points(collection, [("chunk", new, "texte", [1, 0, 0])], "model-b", next_index=True)
    seen, stop = [], threading.Event()

    def search():
        while not stop.is_set():
            seen.append(tuple(p for p, _ in vector_store.search(collection, "texte", [1, 0, 0], 5)))

    thread = threading.Thread(target=search)
    thread.start()
    try:
        for _ in range(20):
            vector_store.swap_with_next(collection)
    finally:
        stop.set()
        thread.join()

    assert seen and set(seen) <= {(old,), (new,)}
