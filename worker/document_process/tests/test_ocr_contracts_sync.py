"""The contracts are copied into the image of each OCR pod (each is built from its own folder): a copy that drifts
from app/ocr/contracts.py is a pod that no longer speaks the same language as the others."""

from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[2]
CANONICAL = WORKER / "document_process" / "app" / "ocr" / "contracts.py"


@pytest.mark.parametrize("pod", ["layout", "ocr", "table", "vision"])
def test_each_pod_has_the_same_contracts(pod):
    copy = WORKER / pod / "app" / "contracts.py"
    assert copy.read_text() == CANONICAL.read_text(), f"cp {CANONICAL} {copy}"
