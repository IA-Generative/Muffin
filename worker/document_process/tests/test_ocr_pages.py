"""The image of a page handed to the OCR pods through S3 (app/ocr/pages.py, RustFsStorage.delete_prefix)."""

import pytest

from app.config import settings
from app.ocr import pages
from app.storage import RustFsStorage


class FakeStorage:
    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.content_types: dict[str, str] = {}

    def put_object(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = data
        self.content_types[key] = content_type

    def get_object(self, key):
        return self.objects[key]

    def delete_prefix(self, prefix):
        gone = [key for key in self.objects if key.startswith(prefix)]
        for key in gone:
            del self.objects[key]
        return len(gone)


def test_the_image_of_a_page_has_a_key_apart_from_the_screenshots():
    key = pages.page_image_key("doc-1", 7)
    assert key == "ocr-pages/doc-1/page-7.png"
    assert not key.startswith("screenshots/")


def test_an_image_goes_in_and_comes_out_by_its_key():
    storage = FakeStorage()
    key = pages.put_page_image(storage, "doc-1", 3, b"png-bytes")
    assert key == pages.page_image_key("doc-1", 3)
    assert storage.content_types[key] == "image/png"
    assert pages.get_page_image(storage, key) == b"png-bytes"


def test_the_images_of_a_document_are_dropped_and_no_other():
    storage = FakeStorage(
        {
            pages.page_image_key("doc-1", 1): b"a",
            pages.page_image_key("doc-1", 2): b"b",
            pages.page_image_key("doc-10", 1): b"not ours: same start, other document",
            "screenshots/doc-1/page-1.png": b"stays",
        }
    )
    assert pages.delete_page_images(storage, "doc-1") == 2
    assert set(storage.objects) == {pages.page_image_key("doc-10", 1), "screenshots/doc-1/page-1.png"}


class _Paginator:
    def __init__(self, pages_):
        self._pages = pages_
        self.asked = None

    def paginate(self, **kwargs):
        self.asked = kwargs
        return iter(self._pages)


class _Client:
    def __init__(self, pages_):
        self.paginator = _Paginator(pages_)
        self.deleted: list[list[dict]] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self.paginator

    def delete_objects(self, Bucket, Delete):
        self.deleted.append(Delete["Objects"])


def _storage(client) -> RustFsStorage:
    storage = RustFsStorage()
    storage._client = client
    storage._bucket_ready = True
    return storage


def test_delete_prefix_deletes_every_page_of_the_listing():
    client = _Client([{"Contents": [{"Key": "p/a"}, {"Key": "p/b"}]}, {"Contents": [{"Key": "p/c"}]}, {}])
    assert _storage(client).delete_prefix("p/") == 3
    assert client.deleted == [[{"Key": "p/a"}, {"Key": "p/b"}], [{"Key": "p/c"}]]
    assert client.paginator.asked == {"Bucket": settings.AWS_BUCKET, "Prefix": "p/"}


def test_delete_prefix_of_nothing_deletes_nothing():
    client = _Client([{}])
    assert _storage(client).delete_prefix("p/") == 0
    assert client.deleted == []


@pytest.mark.parametrize("prefix", ["", "ocr-pages", "ocr-pages/doc-1"])
def test_delete_prefix_only_takes_a_folder(prefix):
    client = _Client([{"Contents": [{"Key": "x"}]}])
    with pytest.raises(ValueError, match="slash"):
        _storage(client).delete_prefix(prefix)
    assert client.deleted == []


def test_the_engine_is_tesseract_until_set_otherwise():
    """Nothing changes for a deployment that sets nothing."""
    assert settings.OCR_ENGINE == "tesseract"
