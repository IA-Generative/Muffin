"""An object of another system (#453) is read where it is, and never deleted."""

from unittest.mock import MagicMock

import pytest

from app.core import storage


@pytest.fixture
def client(monkeypatch):
    fake = MagicMock()
    fake.get_object.return_value = {"Body": MagicMock(read=lambda: b"bytes"), "ContentType": "text/plain"}
    monkeypatch.setattr(storage, "_client", fake)
    monkeypatch.setattr(storage, "_bucket_ready", True)
    return fake


def test_a_key_of_muffin_is_read_in_its_own_bucket(client):
    storage.get_object("documents/c/a.pdf")

    client.get_object.assert_called_once_with(Bucket=storage._settings.AWS_BUCKET, Key="documents/c/a.pdf")


def test_a_foreign_key_is_read_in_the_bucket_it_names(client):
    assert storage.get_object("s3://owui-files/id_test.txt") == (b"bytes", "text/plain")

    client.get_object.assert_called_once_with(Bucket="owui-files", Key="id_test.txt")


def test_a_foreign_key_is_presigned_in_its_bucket(client):
    storage.get_presigned_url("s3://owui-files/id_test.txt")

    assert client.generate_presigned_url.call_args.kwargs["Params"] == {"Bucket": "owui-files", "Key": "id_test.txt"}


def test_a_foreign_object_is_never_deleted(client):
    storage.delete_objects(["documents/c/a.pdf", "s3://owui-files/id_test.txt"])

    [call] = client.delete_objects.call_args_list
    assert call.kwargs["Delete"] == {"Objects": [{"Key": "documents/c/a.pdf"}]}


def test_nothing_is_called_when_only_foreign_objects_are_dropped(client):
    storage.delete_objects(["s3://owui-files/id_test.txt"])

    client.delete_objects.assert_not_called()
