from pathlib import Path

import boto3
from botocore.config import Config

from app.config import settings


class RustFsStorage:
    """What this pod needs of RustFS (S3-compatible): the size of an object and its download. Nothing is written."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            config=Config(
                connect_timeout=settings.STORAGE_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.STORAGE_READ_TIMEOUT_SECONDS,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def size(self, key: str) -> int:
        return self._client.head_object(Bucket=settings.AWS_BUCKET, Key=key)["ContentLength"]

    def download(self, key: str, destination: Path) -> None:
        self._client.download_file(settings.AWS_BUCKET, key, str(destination))


storage = RustFsStorage()
