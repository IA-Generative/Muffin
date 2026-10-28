"""The contracts are copied into the image of each OCR pod (each is built from its own folder): this copy must be
the one of worker/document_process/app/ocr/contracts.py, from which the others are taken."""

from pathlib import Path

WORKER = Path(__file__).resolve().parents[2]


def test_the_contracts_are_the_canonical_ones():
    canonical = WORKER / "document_process" / "app" / "ocr" / "contracts.py"
    copy = Path(__file__).resolve().parents[1] / "app" / "contracts.py"
    assert copy.read_text() == canonical.read_text(), f"cp {canonical} {copy}"
