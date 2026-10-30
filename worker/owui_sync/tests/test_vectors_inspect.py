from unittest.mock import MagicMock

from qdrant_client import models

from app.owui_vectors import CollectionInfo, OwuiVectors, _model_of


def _point(embedding_config) -> models.Record:
    return models.Record(id="p", payload={"text": "t", "metadata": {"embedding_config": embedding_config}})


def _qdrant(*, exists=True, vectors=None, points=()) -> MagicMock:
    client = MagicMock()
    client.collection_exists.return_value = exists
    client.get_collection.return_value.config.params.vectors = vectors or models.VectorParams(
        size=3584, distance=models.Distance.COSINE
    )
    client.scroll.return_value = (list(points), None)
    return client


def test_open_webui_writes_the_model_of_a_chunk_as_a_string_of_a_dict():
    assert _model_of("{'engine': 'openai', 'model': 'bge-multilingual-gemma2'}") == "bge-multilingual-gemma2"
    assert _model_of({"engine": "openai", "model": "bge"}) == "bge"
    assert _model_of("not a dict") is None
    assert _model_of("{'engine': 'openai'}") is None
    assert _model_of(None) is None


def test_the_dimension_and_the_models_of_a_collection_are_read():
    client = _qdrant(points=[_point("{'engine': 'openai', 'model': 'a'}"), _point("{'model': 'b'}"), _point("garbage")])

    info = OwuiVectors(client, prefix="open-webui").inspect("kb1")

    assert info == CollectionInfo(True, 3584, frozenset({"a", "b"}))
    client.collection_exists.assert_called_once_with("open-webui_kb1")


def test_a_collection_that_is_not_there_is_said_so():
    info = OwuiVectors(_qdrant(exists=False), prefix="p").inspect("kb1")

    assert info == CollectionInfo(False, None, frozenset())


def test_named_vectors_have_no_dimension_to_compare():
    client = _qdrant(vectors={"dense": models.VectorParams(size=3, distance=models.Distance.COSINE)})

    assert OwuiVectors(client, prefix="p").inspect("kb1").dimension is None
