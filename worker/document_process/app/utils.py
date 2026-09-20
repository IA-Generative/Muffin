"""Utilitaires transverses du worker document_process.

Fonctions réutilisables qui ne sont ni spécifiques à un format (parsing,
chunking) ni à une tâche Celery (tasks/). Ici : récupération des métadonnées
d'un fichier stocké dans RustFS/S3 via un HEAD.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.storage import storage


@dataclass(frozen=True, slots=True)
class StorageFileInfo:
    """Métadonnées d'un objet stocké dans RustFS/S3, récupérées via un HEAD
    (sans télécharger le contenu).

    Tous les champs sont optionnels : RustFS ne garantit pas la présence de
    chaque métadonnée (un upload sans Content-Type explicite tombe sur
    ``application/octet-stream``, et l'ETag peut être absent sur certains
    backends)."""

    content_type: str | None
    size: int | None
    etag: str | None
    last_modified: str | None
    # Métadonnées personnalisées (x-amz-meta-*) si présentes.
    metadata: dict[str, str]


def get_file_info_from_storage(storage_key: str) -> StorageFileInfo | None:
    """Récupère les métadonnées d'un objet stocké dans RustFS/S3 via un HEAD,
    sans télécharger le contenu.

    Plus léger qu'un GET (pas de body) et plus fiable que l'extension du
    fichier : le Content-Type est celui déclaré par RustFS au moment de
    l'upload.

    Retourne None si le HEAD échoue (objet introuvable, erreur réseau, etc.).
    """

    try:
        response = storage.head_object(storage_key)
    except Exception:
        return None

    # boto3 expose le Content-Type sous la clé "ContentType" (ou
    # "Content-Type" dans les métadonnées brutes).
    content_type = response.get("ContentType") or response.get("Content-Type")
    # ContentLength est un int côté boto3, mais on reste défensif.
    size = response.get("ContentLength")
    etag = response.get("ETag")
    if etag is not None:
        # boto3 renvoie l'ETag entouré de guillemets ("abc123"), on les
        # retire pour avoir une valeur utilisable directement.
        etag = etag.strip('"')
    last_modified = response.get("LastModified")
    if last_modified is not None:
        # datetime -> ISO 8601 string pour sérialisation facile.
        last_modified = last_modified.isoformat()
    # Metadata est un dict séparé pour les x-amz-meta-* personnalisés.
    user_metadata = response.get("Metadata") or {}

    return StorageFileInfo(
        content_type=content_type,
        size=size,
        etag=etag,
        last_modified=last_modified,
        metadata=user_metadata,
    )
