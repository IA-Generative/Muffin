import boto3

from app.config import settings


class RustFsStorage:
    """RustFS is S3-compatible - a plain boto3 client talks to it directly,
    no RustFS-specific SDK needed."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.RUSTFS_ENDPOINT_URL,
            aws_access_key_id=settings.RUSTFS_ACCESS_KEY,
            aws_secret_access_key=settings.RUSTFS_SECRET_KEY,
        )
        self._bucket = settings.RUSTFS_BUCKET
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

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._ensure_bucket()
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)


storage = RustFsStorage()
