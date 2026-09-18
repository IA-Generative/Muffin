import boto3

from app.config import RustFsSettings
from app.logger import logger

_settings = RustFsSettings()
_client = boto3.client(
    "s3",
    endpoint_url=_settings.RUSTFS_ENDPOINT_URL,
    aws_access_key_id=_settings.RUSTFS_ACCESS_KEY,
    aws_secret_access_key=_settings.RUSTFS_SECRET_KEY,
)
_bucket_ready = False


def _ensure_bucket() -> None:
    # Lazy: a real network call at import time would run during test
    # collection, before a test gets to mock this module out.
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        _client.create_bucket(Bucket=_settings.RUSTFS_BUCKET)
    except _client.exceptions.BucketAlreadyOwnedByYou:
        pass
    except Exception:
        pass  # best-effort; a real connectivity/permissions issue still surfaces on the call below
    _bucket_ready = True


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _ensure_bucket()
    _client.put_object(Bucket=_settings.RUSTFS_BUCKET, Key=key, Body=data, ContentType=content_type)


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """A short-lived, unauthenticated link to a stored object (e.g. a page screenshot) - handed
    to the end user in a chat answer, who has no RustFS credentials of their own."""
    return _client.generate_presigned_url(
        "get_object", Params={"Bucket": _settings.RUSTFS_BUCKET, "Key": key}, ExpiresIn=expires_in
    )


def get_object(key: str) -> tuple[bytes, str]:
    """Reads an object's bytes through the backend rather than handing out a presigned RustFS
    URL - used wherever the caller wants every access re-checked against the user's own
    ownership/session on each request (e.g. a document's page screenshots in the document detail
    modal), instead of a link that, once handed out, keeps working on its own until it expires."""
    result = _client.get_object(Bucket=_settings.RUSTFS_BUCKET, Key=key)
    return result["Body"].read(), result.get("ContentType") or "application/octet-stream"


def delete_objects(keys: list[str]) -> None:
    """Best-effort: called after the rows referencing these keys are already
    deleted from Postgres, so a RustFS/network failure here must not roll
    that back or block the request - it just leaves orphaned objects."""
    if not keys:
        return
    try:
        # S3's DeleteObjects caps a single call at 1000 keys.
        for batch_start in range(0, len(keys), 1000):
            batch = keys[batch_start : batch_start + 1000]
            _client.delete_objects(Bucket=_settings.RUSTFS_BUCKET, Delete={"Objects": [{"Key": key} for key in batch]})
    except Exception:
        logger.exception(f"Failed to delete {len(keys)} object(s) from RustFS - they are now orphaned")
