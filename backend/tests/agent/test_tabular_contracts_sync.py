"""The contract of the SQL worker is copied into the image of each side (each is built from its own folder): this copy
must be the one of worker/tabular/app/contracts.py."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def test_the_contracts_are_the_ones_of_the_sql_worker():
    canonical = REPO / "worker" / "tabular" / "app" / "contracts.py"
    if not canonical.exists():
        pytest.skip("the worker's folder is not in this checkout")
    copy = REPO / "backend" / "app" / "agent" / "tabular_contracts.py"
    assert copy.read_text() == canonical.read_text(), f"cp {canonical} {copy}"
