"""How the OCR engine is set where Muffin is deployed (#403): the same in every pod of this image.

The chunking and the summary run in the enrichment pod and fingerprint the extraction they follow (app/reuse.py), which
depends on OCR_ENGINE: a pod that disagrees with the extraction pod breaks the reuse of a file's results across
documents - without a single error. So the values of the chart and the compose file are checked, not trusted."""

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
PODS = ("document_process", "document_enrichment", "index_rebuild")
SERVICES = ("worker-document-process", "worker-document-enrichment", "worker-index-rebuild")


@pytest.fixture(scope="module")
def chart():
    return yaml.safe_load((REPO / "helm" / "values" / "common-values.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((REPO / "docker-compose.yaml").read_text(encoding="utf-8"))["services"]


def test_every_pod_of_the_chart_reads_the_scanned_pages_the_same_way(chart):
    engines = {pod: chart[pod]["env"].get("OCR_ENGINE") for pod in PODS}
    assert set(engines.values()) == {"layout"}, engines


def test_the_chart_runs_the_pods_that_engine_sends_pages_to(chart):
    """OCR_ENGINE=layout with no pod to send to would make every scanned page wait for its timeout."""
    for pod, queue in (("ocr_layout", "document_layout"), ("ocr", "document_ocr")):
        assert queue in chart[pod]["args"], pod
    scaled = {
        obj["spec"]["triggers"][0]["metadata"]["listName"]
        for obj in chart["extraObjects"].values()
        if obj.get("kind") == "ScaledObject"
    }
    assert {"document_layout", "document_ocr"} <= scaled


def test_every_service_of_the_compose_file_reads_the_scanned_pages_the_same_way(compose):
    engines = {name: compose[name]["environment"].get("OCR_ENGINE") for name in SERVICES}
    assert set(engines.values()) == {"layout"}, engines


def test_the_compose_file_starts_the_ocr_pods_with_everything_else(compose):
    for name in ("worker-ocr-layout", "worker-ocr"):
        assert "profiles" not in compose[name], f"{name} would not start with `docker compose up`"
        assert "redis" in compose[name]["depends_on"] and "rustfs" in compose[name]["depends_on"]


def test_the_code_default_stays_the_one_that_changes_nothing():
    """A deployment that configures nothing keeps reading scanned pages with Tesseract."""
    from app.config import WorkerSettings

    assert WorkerSettings.model_fields["OCR_ENGINE"].default == "tesseract"
