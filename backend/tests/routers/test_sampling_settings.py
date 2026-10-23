"""The settings of the sampling of long documents (#372): what is accepted, refused, and merged."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.page_ranges import InvalidPageRangesError, parse_page_ranges
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _settings(client, collection_id, windows):
    return await client.patch(f"/api/collections/{collection_id}/settings", json={"pipeline_windows": windows})


async def _collection(client) -> str:
    return (await client.post("/api/collections")).json()["id"]


async def test_the_sampling_settings_are_saved_and_read_back(client):
    collection_id = await _collection(client)

    response = await _settings(
        client,
        collection_id,
        {
            "sampling_min_pages": 150,
            "summary_mode": "percent",
            "summary_percent": 40,
            "qa_max_questions": 100,
            "extraction_percent": 20,
            "extraction_max_windows": 50,
        },
    )

    assert response.status_code == 200
    windows = response.json()["pipeline_windows"]
    assert windows["sampling_min_pages"] == 150
    assert windows["summary_mode"] == "percent" and windows["summary_percent"] == 40
    assert windows["qa_max_questions"] == 100
    assert windows["extraction_percent"] == 20 and windows["extraction_max_windows"] == 50
    # The settings the worker reads are the same.
    assert windows["summary_pages_per_map"] == 5


async def test_a_cap_is_removed_by_sending_null(client):
    collection_id = await _collection(client)
    await _settings(client, collection_id, {"qa_max_questions": 100, "extraction_max_windows": 10})

    response = await _settings(client, collection_id, {"qa_max_questions": None, "extraction_max_windows": None})

    assert response.status_code == 200
    windows = response.json()["pipeline_windows"]
    assert windows["qa_max_questions"] is None and windows["extraction_max_windows"] is None


@pytest.mark.parametrize(
    "windows",
    [
        {"summary_percent": 0},
        {"summary_percent": 101},
        {"extraction_percent": 0},
        {"extraction_percent": 150},
        {"qa_max_questions": 0},
        {"extraction_max_windows": 0},
        {"sampling_min_pages": 0},
        {"summary_mode": "everything"},
        {"summary_head_percent": 60, "summary_tail_percent": 60},
        {"summary_head_percent": 0, "summary_tail_percent": 0},
        {"summary_mode": "pages"},
        {"summary_mode": "pages", "summary_page_ranges": "three to five"},
        {"summary_page_ranges": "5-2"},
        {"summary_page_ranges": "0-3"},
    ],
)
async def test_settings_that_make_no_sense_are_refused_and_nothing_is_saved(client, windows):
    collection_id = await _collection(client)

    response = await _settings(client, collection_id, windows)

    assert response.status_code == 422
    saved = (await client.get(f"/api/collections/{collection_id}")).json()["pipeline_windows"]
    assert saved["summary_mode"] == "all" and saved["summary_percent"] == 30 and saved["qa_max_questions"] is None


async def test_what_is_valid_only_together_is_checked_against_what_is_saved(client):
    """A start of 70 % is fine alone; added to the 60 % end saved before, it is not."""
    collection_id = await _collection(client)
    assert (await _settings(client, collection_id, {"summary_tail_percent": 60})).status_code == 200

    response = await _settings(client, collection_id, {"summary_head_percent": 70})

    assert response.status_code == 422
    assert "summary_head_percent" in response.json()["detail"]


async def test_a_start_and_an_end_are_accepted_together(client):
    collection_id = await _collection(client)

    response = await _settings(client, collection_id, {"summary_head_percent": 20, "summary_tail_percent": 10})

    assert response.status_code == 200
    windows = response.json()["pipeline_windows"]
    assert (windows["summary_head_percent"], windows["summary_tail_percent"]) == (20, 10)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("7", [(7, 7)]),
        ("1-5", [(1, 5)]),
        ("1-5, 40-45", [(1, 5), (40, 45)]),
        (" 90 - ", [(90, None)]),
        ("3,3-4,", [(3, 3), (3, 4)]),
    ],
)
def test_page_ranges_are_read(text, expected):
    assert parse_page_ranges(text) == expected


@pytest.mark.parametrize("text", ["a", "1-b", "0", "5-2", "1--3", "-4", "1.5", "1 2"])
def test_page_ranges_that_are_not_are_refused(text):
    with pytest.raises(InvalidPageRangesError):
        parse_page_ranges(text)


async def test_the_estimate_follows_the_settings_of_the_collection(client):
    collection_id = await _collection(client)

    default = (await client.get(f"/api/collections/{collection_id}/indexing-estimate", params={"pages": 900})).json()
    # A new collection cuts its chunks with the model (450 calls, on top of the 1 978 of the other steps).
    assert default["chat"]["chunking"] == 450 and default["chat"]["total"] == 2428
    assert default["sampled"] is True and default["collection_max"] == 4

    await _settings(
        client,
        collection_id,
        {"summary_mode": "percent", "summary_percent": 30, "qa_max_questions": 100, "extraction_percent": 20},
    )
    sampled = (await client.get(f"/api/collections/{collection_id}/indexing-estimate", params={"pages": 900})).json()
    assert sampled["chat"] == {"chunking": 450, "summary": 55, "tagging": 1, "qa": 33, "entities": 45, "total": 584}
    assert sampled["embeddings"] == {"summary": 1, "qa_questions": 99}

    short = (await client.get(f"/api/collections/{collection_id}/indexing-estimate", params={"pages": 100})).json()
    assert short["sampled"] is False and short["chat"]["total"] == 268  # 218 + 50 for the chunking


async def test_the_estimate_counts_the_calls_of_the_model_chunking_only_for_that_strategy(client):
    collection_id = await _collection(client)
    url = f"/api/collections/{collection_id}/indexing-estimate"

    llm = (await client.get(url, params={"pages": 900})).json()
    await client.patch(f"/api/collections/{collection_id}/settings", json={"chunking_strategy": "paragraph"})
    paragraph = (await client.get(url, params={"pages": 900})).json()

    assert llm["chat"]["chunking"] == 450
    assert paragraph["chat"]["chunking"] == 0 and paragraph["chat"]["total"] == 1978


@pytest.mark.parametrize("pages", [0, -3, 100_001, "many"])
async def test_the_estimate_refuses_a_number_of_pages_that_makes_no_sense(client, pages):
    collection_id = await _collection(client)

    response = await client.get(f"/api/collections/{collection_id}/indexing-estimate", params={"pages": pages})

    assert response.status_code == 422


async def test_the_estimate_of_a_collection_that_is_not_there_is_a_404(client):
    import uuid

    response = await client.get(f"/api/collections/{uuid.uuid4()}/indexing-estimate", params={"pages": 10})

    assert response.status_code == 404
