"""The blue/green helpers of vector_store (#12) against a stand-in Meilisearch client."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import vector_store

COLLECTION = uuid.uuid4()
ACTIVE = f"chunks_{COLLECTION}"
NEXT = f"chunks_{COLLECTION}_next"


@pytest.fixture
def meili():
    client = MagicMock()
    client.wait_for_task.return_value = SimpleNamespace(status="succeeded", error=None)
    existing: set[str] = set()
    client.existing = existing

    with patch.object(vector_store, "_client", client), patch.object(vector_store, "_index_exists") as exists:
        exists.side_effect = lambda name: name in existing
        yield client


def test_the_swap_exchanges_the_two_indexes_in_one_task_and_waits_for_it(meili):
    meili.existing.update({ACTIVE, NEXT})
    meili.swap_indexes.return_value.task_uid = 7

    vector_store.swap_with_next(COLLECTION)

    meili.swap_indexes.assert_called_once_with([{"indexes": [ACTIVE, NEXT]}])
    assert meili.wait_for_task.call_args.args == (7,)


def test_a_refused_swap_raises_instead_of_pretending_it_happened(meili):
    meili.existing.update({ACTIVE, NEXT})
    meili.wait_for_task.return_value = SimpleNamespace(status="failed", error="no such index")

    with pytest.raises(RuntimeError, match="failed"):
        vector_store.swap_with_next(COLLECTION)


def test_a_collection_with_nothing_indexed_yet_gets_an_empty_active_index_to_swap_with(meili):
    meili.existing.add(NEXT)
    embedders = {"default": SimpleNamespace(dimensions=3)}
    meili.index.return_value.get_settings.return_value = {"embedders": embedders}

    with patch.object(vector_store, "_create_index") as create:
        vector_store.swap_with_next(COLLECTION)

    create.assert_called_once_with(ACTIVE, [0.0, 0.0, 0.0])
    meili.swap_indexes.assert_called_once()


def test_points_are_recorded_with_the_model_that_made_their_vector(meili):
    meili.existing.add(NEXT)
    point_id = uuid.uuid4()

    vector_store.upsert_points(COLLECTION, [("chunk", point_id, "text", [0.1, 0.2])], "new-model", next_index=True)

    meili.index.assert_called_with(NEXT)
    (documents,) = meili.index.return_value.add_documents.call_args.args
    assert documents[0]["id"] == str(point_id) and documents[0]["model"] == "new-model"
    assert documents[0]["_vectors"] == {"default": [0.1, 0.2]}


def test_deleting_a_document_clears_both_indexes(meili):
    meili.existing.update({ACTIVE, NEXT})
    document_id, chunk_id = uuid.uuid4(), uuid.uuid4()

    vector_store.delete_document_embeddings(COLLECTION, document_id, [chunk_id])

    assert [call.args[0] for call in meili.index.call_args_list] == [ACTIVE, NEXT]
    meili.index.return_value.delete_documents.assert_called_with([str(document_id), str(chunk_id)])
