"""The contract of the SQL worker is copied into the image of each side (each is built from its own folder): this copy
must be the one of worker/tabular/app/contracts.py."""

from pathlib import Path


def test_the_contracts_are_the_ones_of_the_sql_worker():
    worker = Path(__file__).resolve().parents[2]
    canonical = worker / "tabular" / "app" / "contracts.py"
    copy = Path(__file__).resolve().parents[1] / "app" / "tabular_contracts.py"
    assert copy.read_text() == canonical.read_text(), f"cp {canonical} {copy}"
