"""Détection des fichiers tabulaires à l'ingestion.

Deux mécanismes complémentaires :
- par extension (rapide, déterministe) ;
- par sniff du contenu (robuste aux extensions manquantes/erronées).

Le sniff reste volontairement conservateur : on ne devine un format tabulaire
que si le contenu ressemble clairement à du CSV/TSV/JSON. Un PDF ou un DOCX ne
sera jamais détecté comme tabulaire, même avec une extension trompeuse.
"""

from __future__ import annotations

import enum
from pathlib import Path

# Seuil en dessous duquel on ne sniff pas : un fichier trop court n'a pas
# assez de signal pour deviner un délimiteur de façon fiable.
SNIFF_MIN_BYTES = 32
SNIFF_READ_BYTES = 8192
# Nombre minimal de lignes avec le même nombre de champs pour qu'on considère
# qu'on a affaire à un CSV/TSV valide (évite les faux positifs sur du prose).
MIN_CONSISTENT_ROWS = 3


class TabularFormat(enum.StrEnum):
    CSV = "csv"
    TSV = "tsv"
    PSV = "psv"
    PARQUET = "parquet"
    JSON = "json"
    JSONL = "jsonl"
    XLSX = "xlsx"


# Extensions -> format. L'extension est le signal primaire : si elle est
# connue et non ambiguë, on ne sniffe pas (sauf pour les .json qui peuvent
# être soit un tableau soit un objet).
_EXTENSION_MAP: dict[str, TabularFormat] = {
    ".csv": TabularFormat.CSV,
    ".tsv": TabularFormat.TSV,
    ".psv": TabularFormat.PSV,
    ".parquet": TabularFormat.PARQUET,
    ".json": TabularFormat.JSON,
    ".jsonl": TabularFormat.JSONL,
    ".ndjson": TabularFormat.JSONL,
    ".xlsx": TabularFormat.XLSX,
}

# Magic bytes pour les formats binaires. Le Parquet commence par "PAR1",
# le XLSX (zip) par "PK\x03\x04" - mais ce dernier est partagé avec tous les
# fichiers zip/office, d'où l'extension comme signal primaire pour le XLSX.
_PARQUET_MAGIC = b"PAR1"

# MIME types supportés pour la validation avant chargement. Le backend
# fournit le mime_type dans les métadonnées du document ; on vérifie qu'il
# est compatible avant de tenter un chargement DuckDB.
_MIME_MAP: dict[str, TabularFormat] = {
    "text/csv": TabularFormat.CSV,
    "text/tab-separated-values": TabularFormat.TSV,
    "application/csv": TabularFormat.CSV,
    "text/plain": TabularFormat.CSV,  # souvent du CSV mal étiqueté
    "application/vnd.ms-excel": TabularFormat.CSV,
    "application/json": TabularFormat.JSON,
    "application/jsonl": TabularFormat.JSONL,
    "application/x-jsonlines": TabularFormat.JSONL,
    "application/x-ndjson": TabularFormat.JSONL,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": TabularFormat.XLSX,
    "application/vnd.apache.parquet": TabularFormat.PARQUET,
    "application/parquet": TabularFormat.PARQUET,
}


def detect_by_extension(filename: str) -> TabularFormat | None:
    """Détection par extension uniquement. Retourne None si l'extension
    n'est pas reconnue comme tabulaire."""
    suffix = Path(filename).suffix.lower()
    return _EXTENSION_MAP.get(suffix)


def _looks_like_delimited(text: str, delimiter: str) -> bool:
    """Vérifie que le texte ressemble à un fichier délimité : au moins
    MIN_CONSISTENT_ROWS lignes avec le même nombre de champs > 1."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_CONSISTENT_ROWS:
        return False
    field_counts = {len(line.split(delimiter)) for line in lines[:20]}
    # Au moins une ligne avec > 1 champ (sinon le délimiteur n'est pas pertinent)
    # et un nombre de champs constant sur l'échantillon.
    return any(count > 1 for count in field_counts) and len(field_counts) == 1


def _looks_like_jsonl(text: str) -> bool:
    """JSONL/NDJSON : chaque ligne est un objet JSON valide. On ne valide pas
    strictement le JSON (trop coûteux pour un sniff), on vérifie juste que la
    majorité des lignes commencent par '{' et finissent par '}'."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_CONSISTENT_ROWS:
        return False
    matches = sum(1 for line in lines[:20] if line.startswith("{") and line.endswith("}"))
    return matches >= len(lines[:20]) * 0.8


def detect_by_content(data: bytes) -> TabularFormat | None:
    """Sniff du contenu pour deviner le format quand l'extension est absente
    ou peu fiable. Conservateur : retourne None en cas de doute."""
    if len(data) < SNIFF_MIN_BYTES:
        return None

    # Parquet : magic bytes non ambiguës.
    if data[:4] == _PARQUET_MAGIC:
        return TabularFormat.PARQUET

    # Formats texte : on décode un échantillon. latin-1 ne lève jamais
    # d'UnicodeDecodeError (un byte = un caractère), suffisant pour sniffer.
    sample = data[:SNIFF_READ_BYTES].decode("latin-1", errors="replace")

    # JSONL avant CSV : un JSONL peut contenir des virgules et ressembler à
    # du CSV si on teste le délimiteur ',' en premier.
    if _looks_like_jsonl(sample):
        return TabularFormat.JSONL

    # Délimiteurs à tester, du plus spécifique au plus générique.
    for delimiter, fmt in (
        ("\t", TabularFormat.TSV),
        ("|", TabularFormat.PSV),
        (",", TabularFormat.CSV),
    ):
        if _looks_like_delimited(sample, delimiter):
            return fmt

    return None


def detect_by_mime(mime_type: str) -> TabularFormat | None:
    """Détection par MIME type. Retourne None si le MIME type n'est pas
    reconnu comme tabulaire. Utilisé pour valider que le format est supporté
    avant toute lecture du fichier."""
    return _MIME_MAP.get(mime_type.lower().strip())


def detect_by_head(storage_key: str) -> TabularFormat | None:
    """Détection via un HEAD S3 : récupère le Content-Type déclaré par
    RustFS/S3 au moment de l'upload, sans télécharger le fichier.

    Plus fiable que l'extension seule (le backend peut avoir mal étiqueté
    le fichier), et plus léger qu'un GET (pas de contenu téléchargé).

    Retourne None si le MIME type n'est pas tabulaire ou si le HEAD échoue.
    """
    from app.utils import get_file_info_from_storage

    info = get_file_info_from_storage(storage_key)
    if info is None or not info.content_type:
        return None
    return detect_by_mime(info.content_type)


def is_supported_mime(mime_type: str) -> bool:
    """Vérifie qu'un MIME type est supporté pour l'analyse tabulaire."""
    return mime_type.lower().strip() in _MIME_MAP


def detect_tabular(filename: str, data: bytes | None = None, storage_key: str | None = None) -> TabularFormat | None:
    """Point d'entrée : détermine si un fichier est tabulaire et dans quel
    format. Ordre de détection :

    1. Extension du fichier (signal primaire, rapide et déterministe).
    2. HEAD S3 (Content-Type déclaré par RustFS, sans télécharger le fichier).
    3. Sniff du contenu (robuste aux extensions manquantes/erronées).

    Le sniff du contenu (3) n'est déclenché que si ``data`` est fourni :
    permet d'appeler ``detect_tabular(filename, storage_key=...)`` sans GET
    préalable quand on veut juste tester extension + HEAD.

    Retourne None pour les fichiers non tabulaires (PDF, DOCX, images, etc.)
    - le pipeline classique (liteparse) les prend en charge.
    """
    fmt = detect_by_extension(filename)
    if fmt is not None:
        return fmt
    if storage_key is not None:
        fmt = detect_by_head(storage_key)
        if fmt is not None:
            return fmt
    if data is not None:
        return detect_by_content(data)
    return None
