from collections.abc import Iterator
from typing import BinaryIO

import boto3

from app.config import RustFsSettings
from app.logger import logger

_settings = RustFsSettings()
_client = boto3.client(
    "s3",
    endpoint_url=_settings.AWS_ENDPOINT_URL,
    aws_access_key_id=_settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=_settings.AWS_SECRET_ACCESS_KEY,
)
_bucket_ready = False

# A key may name an object of another system, in its own bucket, as that system writes it: `s3://<bucket>/<key>`
# (a file copied from Open WebUI, #453). Muffin reads it where it is, and never deletes it - it is not Muffin's.
_FOREIGN_PREFIX = "s3://"


def is_foreign(key: str) -> bool:
    return key.startswith(_FOREIGN_PREFIX)


def _location(key: str) -> tuple[str, str]:
    """(bucket, key) of an object: Muffin's own bucket, or the one a foreign key names."""
    if is_foreign(key):
        bucket, _, name = key.removeprefix(_FOREIGN_PREFIX).partition("/")
        return bucket, name
    return _settings.AWS_BUCKET, key


def _ensure_bucket() -> None:
    # Lazy: a real network call at import time would run during test
    # collection, before a test gets to mock this module out.
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        _client.create_bucket(Bucket=_settings.AWS_BUCKET)
    except _client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception:
        pass  # best-effort; a real connectivity/permissions issue still surfaces on the call below
    _bucket_ready = True


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _ensure_bucket()
    _client.put_object(Bucket=_settings.AWS_BUCKET, Key=key, Body=data, ContentType=content_type)


def upload_fileobj(key: str, fileobj: BinaryIO, content_type: str = "application/octet-stream") -> None:
    """Streams a file-like object to RustFS in parts, never holding it whole in memory - for
    uploads too large for put_object's single in-memory body (a ZIP import, #223)."""
    _ensure_bucket()
    _client.upload_fileobj(fileobj, _settings.AWS_BUCKET, key, ExtraArgs={"ContentType": content_type})


def copy_object(source_key: str, target_key: str) -> None:
    """Copies an object inside the bucket, server side: the bytes never come through the backend. A
    document that reuses another's page screenshots gets copies of its own (#300) - deleting a document
    deletes its objects, so one shared between two would vanish from the other."""
    _ensure_bucket()
    source_bucket, source_name = _location(source_key)
    _client.copy_object(
        Bucket=_settings.AWS_BUCKET,
        Key=target_key,
        CopySource={"Bucket": source_bucket, "Key": source_name},
    )


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """A short-lived, unauthenticated link to a stored object (e.g. a page screenshot) - handed
    to the end user in a chat answer, who has no RustFS credentials of their own."""
    bucket, name = _location(key)
    return _client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": name},
        ExpiresIn=expires_in,
    )


def get_object(key: str) -> tuple[bytes, str]:
    """Reads an object's bytes through the backend rather than handing out a presigned RustFS
    URL - used wherever the caller wants every access re-checked against the user's own
    ownership/session on each request (e.g. a document's page screenshots in the document detail
    modal), instead of a link that, once handed out, keeps working on its own until it expires.
    """
    bucket, name = _location(key)
    result = _client.get_object(Bucket=bucket, Key=name)
    return (
        result["Body"].read(),
        result.get("ContentType") or "application/octet-stream",
    )


def open_object(key: str, chunk_size: int = 64 * 1024) -> tuple[Iterator[bytes], str, int | None]:
    """An object as a stream of chunks, with its content type and its size - for a file that may be large, which
    `get_object` would read whole into memory. The caller iterates it to the end (or closes it)."""
    bucket, name = _location(key)
    result = _client.get_object(Bucket=bucket, Key=name)
    body = result["Body"]

    def chunks() -> Iterator[bytes]:
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

    return chunks(), result.get("ContentType") or "application/octet-stream", result.get("ContentLength")


def delete_objects(keys: list[str]) -> None:
    """Best-effort: called after the rows referencing these keys are already
    deleted from Postgres, so a RustFS/network failure here must not roll
    that back or block the request - it just leaves orphaned objects."""
    keys = [key for key in keys if not is_foreign(key)]
    if not keys:
        return
    try:
        # S3's DeleteObjects caps a single call at 1000 keys.
        for batch_start in range(0, len(keys), 1000):
            batch = keys[batch_start : batch_start + 1000]
            _client.delete_objects(
                Bucket=_settings.AWS_BUCKET,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )
    except Exception:
        logger.exception(f"Failed to delete {len(keys)} object(s) from RustFS - they are now orphaned")
