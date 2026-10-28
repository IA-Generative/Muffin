import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.contracts import QueryRequest
from app.limits import QueryLimits
from app.tasks import execute

COLLECTION = str(uuid.uuid4())
OTHER_COLLECTION = str(uuid.uuid4())


def key(collection: str = COLLECTION, index: int = 0, document: str | None = None) -> str:
    return f"documents/{collection}/{document or uuid.uuid4()}/tables/{index}.parquet"


class FakeStorage:
    """The typed copies by key, written where the pod is asked to download them."""

    def __init__(self, tables: dict[str, pa.Table]) -> None:
        self.tables = tables
        self.downloads: list[str] = []

    def size(self, key: str) -> int:
        if key not in self.tables:
            raise KeyError(key)
        return 1000

    def download(self, key: str, destination: Path) -> None:
        self.downloads.append(key)
        pq.write_table(self.tables[key], destination)


def sheet(name: str, key_: str, table: pa.Table) -> dict:
    return {
        "name": name,
        "key": key_,
        "columns": [{"name": n, "sql_type": str(table.schema.field(n).type)} for n in table.column_names],
    }


@pytest.fixture
def sales() -> pa.Table:
    return pa.table({"region": ["Nord", "Sud", "Nord"], "montant": [10.0, 20.0, 30.0], "client": [1, 2, 1]})


@pytest.fixture
def clients() -> pa.Table:
    return pa.table({"id": [1, 2], "nom": ["Ann", "Bob"]})


def request(sql: str, files: list[dict], collections: list[str] | None = None) -> dict:
    return {"sql": sql, "collection_ids": collections or [COLLECTION], "files": files}


def test_a_query_over_one_sheet(sales, tmp_path) -> None:
    k = key()
    payload = request(
        'SELECT region, SUM(montant) AS total FROM f1."Ventes" GROUP BY 1 ORDER BY 1',
        [{"ref": "f1", "sheets": [sheet("Ventes", k, sales)]}],
    )

    result = execute(payload, FakeStorage({k: sales}), QueryLimits(), str(tmp_path))

    assert result["status"] == "completed"
    assert result["rows"] == [["Nord", 40.0], ["Sud", 20.0]]
    assert [c["name"] for c in result["columns"]] == ["region", "total"]
    assert result["truncated"] is False and result["duration_ms"] >= 0


def test_a_join_across_two_files(sales, clients, tmp_path) -> None:
    k1, k2 = key(), key(document=str(uuid.uuid4()))
    payload = request(
        'SELECT c.nom, SUM(v.montant) FROM f1."Ventes" v JOIN f2."Clients" c ON c.id = v.client GROUP BY 1 ORDER BY 1',
        [
            {"ref": "f1", "sheets": [sheet("Ventes", k1, sales)]},
            {"ref": "f2", "sheets": [sheet("Clients", k2, clients)]},
        ],
    )

    result = execute(payload, FakeStorage({k1: sales, k2: clients}), QueryLimits(), str(tmp_path))

    assert result["rows"] == [["Ann", 40.0], ["Bob", 20.0]]


def test_a_wrong_sql_fails_with_what_can_be_queried(sales, tmp_path) -> None:
    k = key()
    payload = request('SELECT nope FROM f1."Ventes"', [{"ref": "f1", "sheets": [sheet("Ventes", k, sales)]}])

    result = execute(payload, FakeStorage({k: sales}), QueryLimits(), str(tmp_path))

    assert result["status"] == "failed"
    assert "nope" in result["message"]
    assert result["tables"][0]["table"] == '"f1"."Ventes"'
    assert [c["name"] for c in result["tables"][0]["columns"]] == ["region", "montant", "client"]


def test_a_key_outside_the_expected_prefix_is_refused_and_nothing_is_downloaded(sales, tmp_path) -> None:
    store = FakeStorage({})
    for bad in (
        "../../etc/passwd",
        f"documents/{COLLECTION}/{uuid.uuid4()}/tables/../../../other/0.parquet",
        f"documents/{COLLECTION}/{uuid.uuid4()}/original.pdf",
        f"charts/{COLLECTION}/x/0.parquet",
        f"/documents/{COLLECTION}/{uuid.uuid4()}/tables/0.parquet",
    ):
        payload = request("SELECT 1", [{"ref": "f1", "sheets": [sheet("Ventes", bad, sales)]}])

        result = execute(payload, store, QueryLimits(), str(tmp_path))

        assert result["status"] == "failed" and "invalide" in result["message"], bad
    assert store.downloads == []


def test_a_key_of_another_collection_is_refused(sales, tmp_path) -> None:
    k = key(OTHER_COLLECTION)
    store = FakeStorage({k: sales})
    payload = request("SELECT 1", [{"ref": "f1", "sheets": [sheet("Ventes", k, sales)]}])

    result = execute(payload, store, QueryLimits(), str(tmp_path))

    assert result["status"] == "failed" and "invalide" in result["message"]
    assert store.downloads == []


def test_a_request_of_a_newer_schema_is_refused(sales, tmp_path) -> None:
    k = key()
    payload = {**request("SELECT 1", [{"ref": "f1", "sheets": [sheet("A", k, sales)]}]), "schema_version": 99}

    assert execute(payload, FakeStorage({k: sales}), QueryLimits(), str(tmp_path))["status"] == "failed"


def test_unknown_fields_are_ignored(sales) -> None:
    k = key()
    payload = {**request("SELECT 1", [{"ref": "f1", "sheets": [sheet("A", k, sales)]}]), "future": True}

    assert QueryRequest.model_validate(payload).sql == "SELECT 1"


@pytest.mark.parametrize("ref", ["f0", "F1", "f1;", "f1.x", "schema", ""])
def test_a_file_reference_is_f_and_a_number(ref, sales, tmp_path) -> None:
    k = key()
    payload = request("SELECT 1", [{"ref": ref, "sheets": [sheet("A", k, sales)]}])

    assert execute(payload, FakeStorage({k: sales}), QueryLimits(), str(tmp_path))["status"] == "failed"


def test_two_files_cannot_share_a_reference(sales, tmp_path) -> None:
    k1, k2 = key(), key()
    payload = request(
        "SELECT 1",
        [{"ref": "f1", "sheets": [sheet("A", k1, sales)]}, {"ref": "f1", "sheets": [sheet("B", k2, sales)]}],
    )

    assert execute(payload, FakeStorage({k1: sales, k2: sales}), QueryLimits(), str(tmp_path))["status"] == "failed"


def test_too_many_files_are_refused_before_downloading(sales, tmp_path) -> None:
    keys = [key() for _ in range(3)]
    store = FakeStorage({k: sales for k in keys})
    files = [{"ref": f"f{i + 1}", "sheets": [sheet("A", k, sales)]} for i, k in enumerate(keys)]

    result = execute(request("SELECT 1", files), store, QueryLimits(max_files=2), str(tmp_path))

    assert result["status"] == "failed" and "Trop de fichiers" in result["message"]
    assert store.downloads == []


def test_too_much_data_is_refused_before_downloading(sales, tmp_path) -> None:
    k = key()
    store = FakeStorage({k: sales})
    payload = request("SELECT 1", [{"ref": "f1", "sheets": [sheet("A", k, sales)]}])

    result = execute(payload, store, QueryLimits(max_table_bytes=10), str(tmp_path))

    assert result["status"] == "failed" and "volumineux" in result["message"]
    assert store.downloads == []


def test_a_sheet_that_cannot_be_read_fails_without_leaking_the_error(sales, tmp_path) -> None:
    k = key()
    payload = request("SELECT 1", [{"ref": "f1", "sheets": [sheet("A", k, sales)]}])

    result = execute(payload, FakeStorage({}), QueryLimits(), str(tmp_path))

    assert result["status"] == "failed" and "pas lisible" in result["message"] and k not in result["message"]


def test_a_corrupt_parquet_is_a_failure_not_a_crash(sales, tmp_path) -> None:
    class Corrupt(FakeStorage):
        def download(self, key: str, destination: Path) -> None:
            destination.write_bytes(b"not parquet")

    k = key()
    payload = request('SELECT * FROM f1."A"', [{"ref": "f1", "sheets": [sheet("A", k, sales)]}])

    result = execute(payload, Corrupt({k: sales}), QueryLimits(), str(tmp_path))

    assert result["status"] == "failed"


def test_the_private_folder_is_removed_after_the_query(sales, tmp_path) -> None:
    k = key()
    payload = request('SELECT * FROM f1."A"', [{"ref": "f1", "sheets": [sheet("A", k, sales)]}])

    execute(payload, FakeStorage({k: sales}), QueryLimits(), str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_a_sheet_the_sql_cannot_reach_by_another_file_name(sales, clients, tmp_path) -> None:
    """Each file is its own schema: f1's sheets are not visible as f2's."""
    k1, k2 = key(), key()
    files = [
        {"ref": "f1", "sheets": [sheet("Ventes", k1, sales)]},
        {"ref": "f2", "sheets": [sheet("Clients", k2, clients)]},
    ]

    store = FakeStorage({k1: sales, k2: clients})

    result = execute(request('SELECT * FROM f2."Ventes"', files), store, QueryLimits(), str(tmp_path))

    assert result["status"] == "failed" and "Ventes" in result["message"]
