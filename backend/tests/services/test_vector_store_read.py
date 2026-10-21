"""Reading points back from Meilisearch, for a document that reuses another's vectors (#300)."""

import uuid
from types import SimpleNamespace

import pytest
from meilisearch.errors import MeilisearchApiError

from app.services import vector_store

POINT = uuid.uuid4()
OTHER = uuid.uuid4()


class FakeIndex:
    def __init__(self, points):
        self.points = points
        self.asked = []

    def get_document(self, point_id, parameters):
        self.asked.append((point_id, parameters))
        if point_id not in self.points:
            error = MeilisearchApiError.__new__(MeilisearchApiError)
            error.code = "document_not_found"
            raise error
        return self.points[point_id]


class FakeClient:
    def __init__(self, index, pending=0):
        self._index = index
        self.pending = pending
        self.task_queries = []

    def index(self, name):
        return self._index

    def get_tasks(self, parameters):
        self.task_queries.append(parameters)
        if self.pending:
            self.pending -= 1
            return SimpleNamespace(results=[object()])
        return SimpleNamespace(results=[])


@pytest.fixture
def meili(monkeypatch):
    def install(points, pending=0):
        index = FakeIndex(points)
        client = FakeClient(index, pending)
        monkeypatch.setattr(vector_store, "_client", client)
        monkeypatch.setattr(vector_store, "_index_exists", lambda name: True)
        monkeypatch.setattr(vector_store.time, "sleep", lambda seconds: None)
        return index, client

    return install


def _point(embedding, model="model-a"):
    return {"id": "x", "text": "t", "model": model, "_vectors": {"default": {"embeddings": [embedding]}}}


def test_the_vector_and_the_model_that_made_it_are_read_back(meili):
    index, _ = meili({str(POINT): _point([0.1, 0.2], "model-a")})

    assert vector_store.read_vectors(uuid.uuid4(), [POINT]) == {POINT: ([0.1, 0.2], "model-a")}
    # Meilisearch only returns vectors when asked to.
    assert index.asked == [(str(POINT), {"retrieveVectors": "true"})]


def test_a_point_that_is_not_there_is_simply_absent(meili):
    meili({str(POINT): _point([0.1])})

    assert vector_store.read_vectors(uuid.uuid4(), [POINT, OTHER]) == {POINT: ([0.1], "model-a")}


def test_a_point_with_no_vector_is_absent(meili):
    meili({str(POINT): {"id": "x", "_vectors": {"default": {"embeddings": []}}}})

    assert vector_store.read_vectors(uuid.uuid4(), [POINT]) == {}


def test_a_point_indexed_before_the_model_was_recorded_has_no_model(meili):
    meili({str(POINT): {"id": "x", "_vectors": {"default": {"embeddings": [[0.5]]}}}})

    assert vector_store.read_vectors(uuid.uuid4(), [POINT]) == {POINT: ([0.5], None)}


def test_nothing_is_read_when_there_is_no_index_or_no_point(monkeypatch):
    monkeypatch.setattr(vector_store, "_index_exists", lambda name: False)

    assert vector_store.read_vectors(uuid.uuid4(), [POINT]) == {}
    assert vector_store.read_vectors(uuid.uuid4(), []) == {}


def test_it_waits_for_what_was_written_just_before_to_be_indexed(meili):
    """Meilisearch returns from a write once it is queued: read at once, the point is not there yet."""
    _, client = meili({str(POINT): _point([0.1])}, pending=3)

    assert vector_store.read_vectors(uuid.uuid4(), [POINT]) == {POINT: ([0.1], "model-a")}

    assert len(client.task_queries) == 4  # three times busy, then settled
    assert client.task_queries[0]["statuses"] == ["enqueued", "processing"]


def test_an_index_that_never_settles_fails_the_read_rather_than_returning_a_partial_copy(meili, monkeypatch):
    meili({str(POINT): _point([0.1])}, pending=10**6)
    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(vector_store.time, "monotonic", lambda: next(clock))

    with pytest.raises(TimeoutError):
        vector_store.read_vectors(uuid.uuid4(), [POINT])
