import base64
import io
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

from app.chart_task import execute_chart

COLLECTION = str(uuid.uuid4())
KEY = f"documents/{COLLECTION}/{uuid.uuid4()}/tables/0.parquet"
TABLE = pa.table({"region": ["Nord", "Sud", "Est"], "montant": [10.0, 20.0, 5.0]})


class Store:
    def size(self, key: str) -> int:
        return 1000

    def download(self, key: str, destination: Path) -> None:
        pq.write_table(TABLE, destination)


def request(sql='SELECT region, montant FROM f1."Ventes"', **spec) -> dict:
    return {
        "sql": sql,
        "collection_ids": [COLLECTION],
        "files": [
            {
                "ref": "f1",
                "sheets": [
                    {
                        "name": "Ventes",
                        "key": KEY,
                        "columns": [
                            {"name": "region", "sql_type": "VARCHAR"},
                            {"name": "montant", "sql_type": "DOUBLE"},
                        ],
                    }
                ],
            }
        ],
        "spec": {"type": "bar", "x": "region", "y": ["montant"], "title": "Montant par région", **spec},
    }


def test_a_chart_is_drawn_from_the_query_and_given_back_as_a_png(tmp_path) -> None:
    result = execute_chart(request(), Store(), str(tmp_path))

    assert result["status"] == "completed" and result["rows"] == 3 and result["truncated"] is False
    image = Image.open(io.BytesIO(base64.b64decode(result["png_base64"])))
    assert image.format == "PNG" and image.size == (result["width"], result["height"]) == (900, 540)
    assert list(tmp_path.iterdir()) == []


def test_a_column_that_is_not_in_the_result_fails_with_the_columns_of_the_result(tmp_path) -> None:
    result = execute_chart(request(y=["chiffre"]), Store(), str(tmp_path))

    assert result["status"] == "failed" and "chiffre" in result["message"]
    assert [c["name"] for c in result["columns"]] == ["region", "montant"]


def test_a_sql_that_fails_is_a_failure_that_says_so(tmp_path) -> None:
    result = execute_chart(request(sql='SELECT nope FROM f1."Ventes"'), Store(), str(tmp_path))

    assert result["status"] == "failed" and "nope" in result["message"]


def test_an_inconsistent_spec_is_refused_with_what_to_change(tmp_path) -> None:
    result = execute_chart(request(type="pie", y=["montant", "montant"]), Store(), str(tmp_path))

    assert result["status"] == "failed" and "exactly one `y`" in result["message"]


def test_a_key_outside_the_collection_is_refused_before_any_download(tmp_path) -> None:
    payload = request()
    payload["collection_ids"] = [str(uuid.uuid4())]

    assert execute_chart(payload, Store(), str(tmp_path))["status"] == "failed"


def test_more_points_than_the_agent_sees_are_drawn(tmp_path) -> None:
    sql = "SELECT i * 1.0 AS region, (i % 30) * 1.0 AS montant FROM range(3000) t(i)"

    result = execute_chart(request(sql=sql, type="scatter", x="region"), Store(), str(tmp_path))

    assert result["status"] == "completed" and result["rows"] == 3000
