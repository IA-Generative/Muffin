import io
from typing import BinaryIO

import boto3
from botocore.config import Config

from app.config import settings

# What a RangeReader fetches at a time: a ZIP is read in small pieces - its end, its directory, a member's
# header, then its data - and each piece comes out of the block already fetched when it can.
_RANGE_BLOCK_BYTES = 8 * 1024 * 1024


class RangeReader(io.RawIOBase):
    """A read-only, seekable file over an object, read by ranges - what zipfile needs to read the directory
    of an archive and the members it is asked for, without the archive being downloaded whole (#334)."""

    def __init__(self, client, bucket: str, key: str, size: int, block_bytes: int = _RANGE_BLOCK_BYTES) -> None:
        super().__init__()
        self._client, self._bucket, self._key, self._size = client, bucket, key, size
        self._block_bytes = block_bytes
        self._position = 0
        self._block_start = 0
        self._block = b""

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self._size}[whence]
        self._position = max(base + offset, 0)
        return self._position

    def readinto(self, buffer) -> int:
        wanted = min(len(buffer), self._size - self._position)
        if wanted <= 0:
            return 0
        written = 0
        while written < wanted:
            if not self._block_start <= self._position < self._block_start + len(self._block):
                self._fetch(self._position)
            offset = self._position - self._block_start
            chunk = self._block[offset : offset + wanted - written]
            buffer[written : written + len(chunk)] = chunk
            written += len(chunk)
            self._position += len(chunk)
        return written

    def _fetch(self, start: int) -> None:
        end = min(start + self._block_bytes, self._size) - 1
        response = self._client.get_object(Bucket=self._bucket, Key=self._key, Range=f"bytes={start}-{end}")
        self._block_start, self._block = start, response["Body"].read()


class RustFsStorage:
    """RustFS is S3-compatible - a plain boto3 client talks to it directly,
    no RustFS-specific SDK needed."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            # Explicit (#294): the read timeout bounds the wait for the next bytes, not a transfer,
            # so a large file still goes through; an unreachable storage fails after a few retries
            # instead of holding a slot.
            config=Config(
                connect_timeout=settings.STORAGE_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.STORAGE_READ_TIMEOUT_SECONDS,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        self._bucket = settings.AWS_BUCKET
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        # Lazy, not in __init__: a real network call there would fire at
        # import time (import app.tasks -> import app.storage), before tests
        # get a chance to monkeypatch this object out.
        if self._bucket_ready:
            return
        try:
            self._client.create_bucket(Bucket=self._bucket)
        except self._client.exceptions.BucketAlreadyOwnedByYou:
            pass
        except Exception:
            pass  # best-effort; a real connectivity/permissions issue still surfaces on the call below
        self._bucket_ready = True

    def get_object(self, key: str) -> bytes:
        self._ensure_bucket()
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def head_object(self, key: str) -> dict:
        """Récupère les métadonnées d'un objet (Content-Type, taille, etc.)
        sans télécharger le contenu. Utilise HEAD via boto3 - un ordre de
        grandeur plus léger qu'un GET pour valider le type d'un fichier."""
        self._ensure_bucket()
        return self._client.head_object(Bucket=self._bucket, Key=key)

    def download_fileobj(self, key: str, fileobj: BinaryIO) -> None:
        """Streams an object into a file-like object in parts - for an archive too large to read
        in one go (a ZIP import, #223)."""
        self._ensure_bucket()
        self._client.download_fileobj(self._bucket, key, fileobj)

    def open_seekable(self, key: str) -> RangeReader:
        """The object as a file that can be read anywhere, by ranges - for an archive too large to be
        downloaded by each task that reads a part of it (#334). Close it when done."""
        self._ensure_bucket()
        size = self.head_object(key)["ContentLength"]
        return RangeReader(self._client, self._bucket, key, size)

    def upload_fileobj(self, key: str, fileobj: BinaryIO, content_type: str = "application/octet-stream") -> None:
        """Streams a file-like object to RustFS in parts, never holding it whole in memory - a file
        extracted from a ZIP import (#223) can be large."""
        self._ensure_bucket()
        self._client.upload_fileobj(fileobj, self._bucket, key, ExtraArgs={"ContentType": content_type})

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._ensure_bucket()
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def delete_prefix(self, prefix: str) -> int:
        """Deletes every object whose key starts with `prefix`, and gives how many there were. The prefix is
        required to be a folder (ending with a slash): "" or "ocr-pages" would reach far more than meant."""
        if not prefix.endswith("/"):
            raise ValueError(f"{prefix!r} is not a folder to delete: it must end with a slash")
        self._ensure_bucket()
        deleted = 0
        for page in self._client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
        return deleted


storage = RustFsStorage()
