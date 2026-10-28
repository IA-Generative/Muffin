import boto3
from botocore.config import Config

from app.config import settings


class RustFsStorage:
    """What this pod needs of RustFS (S3-compatible): reading the image of a page."""

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

    def get_object(self, key: str) -> bytes:
        return self._client.get_object(Bucket=settings.AWS_BUCKET, Key=key)["Body"].read()


storage = RustFsStorage()
