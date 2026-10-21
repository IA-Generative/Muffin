"""Reading a ZIP archive safely for a collection import (#223).

Pure functions over ``zipfile`` - no backend or storage call - so every rule here is testable
with an archive built in memory. ``plan_import`` decides, from the archive's directory alone,
which files to import into which folder and why the others are skipped; ``extract_member`` then
copies one of them, chunk by chunk, into a file-like object, with a hard cap, never trusting the
sizes the archive declares.

Nothing in an archive is ever written to the local filesystem under its own path: the importer
copies each member into an anonymous temporary spool (memory, then a temporary file past a few MB)
and stores it in RustFS under a key it builds. Neither the archive nor a large member is ever held
whole in memory.
"""

import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import BinaryIO

from app.tabular.detect import _EXTENSION_MAP as _TABULAR_EXTENSIONS

# What the document pipeline can process: liteparse's PDF/Office/image formats, Markdown and text, and
# the tabular formats (app/tabular/detect.py). Anything else would only fail later, in
# process_document - it's listed as skipped instead.
SUPPORTED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".odt",
        ".rtf",
        ".ppt",
        ".pptx",
        ".odp",
        ".xls",
        ".ods",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".gif",
        ".webp",
        ".md",
        ".txt",
        *_TABULAR_EXTENSIONS,
    }
)
_NESTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"})
# OS metadata, not user content - dropped silently rather than listed as skipped, or a ZIP made
# on a Mac would report as many skipped files as real ones (an AppleDouble twin for each).
_SYSTEM_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_SYSTEM_DIRS = frozenset({"__macosx"})
_MAX_NAME_LENGTH = 200
_UTF8_FLAG = 0x800
_SYMLINK_MODE = 0o120000
_FILE_TYPE_MASK = 0o170000
_WINDOWS_DRIVE = re.compile(r"^[a-zA-Z]:")


@dataclass(frozen=True)
class ZipLimits:
    max_files: int
    max_total_bytes: int
    max_file_bytes: int
    max_ratio: int
    max_depth: int


@dataclass(frozen=True)
class PlannedFile:
    info: zipfile.ZipInfo
    # Folder names from the root of the archive down to the file's folder - () for the root.
    folder: tuple[str, ...]
    name: str


@dataclass
class ImportPlan:
    # Every folder to create, parents always before their sub-folders. Only folders that end up
    # holding a file somewhere below them: an empty folder creates nothing.
    folders: list[tuple[str, ...]] = field(default_factory=list)
    files: list[PlannedFile] = field(default_factory=list)
    # {"path", "reason"} - shown to the user in the import summary, hence in French.
    skipped: list[dict[str, str]] = field(default_factory=list)


class ArchiveRejectedError(Exception):
    """The whole archive is refused (too many files, too large once expanded) - the message is
    shown to the user as is."""


class MemberSkippedError(Exception):
    """One member couldn't be read safely - the message is its reason in the summary."""


def decode_name(info: zipfile.ZipInfo) -> str:
    """A member's path as text. Without the UTF-8 flag, zipfile decodes names as CP437 (the ZIP
    default), but most archivers really wrote UTF-8 - re-decoded as such when that works."""
    if info.flag_bits & _UTF8_FLAG:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except UnicodeError:
        return info.filename


def split_safe_path(raw: str) -> list[str] | None:
    """The path's parts, or None when it would escape the archive's root (Zip Slip): an absolute
    path, a Windows drive, or any ".." part. Backslashes count as separators."""
    path = raw.replace("\\", "/")
    if path.startswith("/") or _WINDOWS_DRIVE.match(path):
        return None
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return None
    return parts


def clean_part(part: str) -> str:
    """NFC-normalized, without control/format characters, at most _MAX_NAME_LENGTH characters
    (the extension kept when it has to be shortened)."""
    text = unicodedata.normalize("NFC", part)
    text = "".join(char for char in text if unicodedata.category(char) not in ("Cc", "Cf")).strip()
    if len(text) <= _MAX_NAME_LENGTH:
        return text
    suffix = PurePosixPath(text).suffix
    if len(suffix) >= _MAX_NAME_LENGTH:
        return text[:_MAX_NAME_LENGTH]
    return text[: _MAX_NAME_LENGTH - len(suffix)] + suffix


def is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & _FILE_TYPE_MASK == _SYMLINK_MODE


def _is_system_file(parts: list[str]) -> bool:
    return (
        any(part.lower() in _SYSTEM_DIRS for part in parts)
        or parts[-1].lower() in _SYSTEM_NAMES
        or parts[-1].startswith("._")
    )


def plan_import(infos: list[zipfile.ZipInfo], limits: ZipLimits) -> ImportPlan:
    """What to import, from the archive's directory alone. Raises ArchiveRejectedError when the
    archive as a whole is over its limits - nothing is created then."""
    members = [info for info in infos if not info.is_dir()]
    if len(members) > limits.max_files:
        raise ArchiveRejectedError(
            f"L'archive contient {len(members)} fichiers, au-delà de la limite de {limits.max_files}."
        )
    if sum(info.file_size for info in members) > limits.max_total_bytes:
        raise ArchiveRejectedError("Une fois décompressée, l'archive dépasse la taille maximale autorisée.")

    plan = ImportPlan()

    def skip(path: str, reason: str) -> None:
        plan.skipped.append({"path": path, "reason": reason})

    for info in members:
        raw = decode_name(info)
        parts = split_safe_path(raw)
        if parts is None:
            skip(raw, "chemin en dehors de l'archive")
            continue
        parts = [clean_part(part) for part in parts]
        if not parts or any(not part for part in parts):
            skip(raw, "nom invalide")
            continue
        if _is_system_file(parts):
            continue
        path = "/".join(parts)
        if any(part.startswith(".") for part in parts):
            skip(path, "fichier ou dossier caché")
        elif is_symlink(info):
            skip(path, "lien symbolique")
        elif len(parts) - 1 > limits.max_depth:
            skip(path, "dossier trop profond")
        elif PurePosixPath(parts[-1]).suffix.lower() in _NESTED_ARCHIVE_EXTENSIONS:
            skip(path, "archive imbriquée")
        elif PurePosixPath(parts[-1]).suffix.lower() not in SUPPORTED_EXTENSIONS:
            skip(path, "type de fichier non pris en charge")
        elif info.file_size == 0:
            skip(path, "fichier vide")
        elif info.file_size > limits.max_file_bytes:
            skip(path, "fichier trop volumineux")
        elif info.file_size > limits.max_ratio * max(info.compress_size, 1):
            skip(path, "taux de compression suspect")
        else:
            plan.files.append(PlannedFile(info=info, folder=tuple(parts[:-1]), name=parts[-1]))

    folders = {file.folder[:depth] for file in plan.files for depth in range(1, len(file.folder) + 1)}
    plan.folders = sorted(folders, key=lambda folder: (len(folder), folder))
    return plan


def extract_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int, sink: BinaryIO, chunk_size: int = 1024 * 1024
) -> int:
    """Copies a member's content into `sink`, chunk by chunk and never past `cap` bytes, whatever
    its header claims; returns how many bytes were written. A corrupted member (bad CRC, truncated
    data) is skipped, not the whole archive - what was already written to `sink` is then the
    caller's to discard."""
    written = 0
    try:
        with archive.open(info) as member:
            while chunk := member.read(chunk_size):
                written += len(chunk)
                if written > cap:
                    raise MemberSkippedError("contenu plus volumineux qu'annoncé")
                sink.write(chunk)
    except RuntimeError as error:
        # zipfile's way of saying the member is password-protected.
        raise MemberSkippedError("fichier chiffré") from error
    except NotImplementedError as error:
        raise MemberSkippedError("méthode de compression non prise en charge") from error
    except (zipfile.BadZipFile, EOFError, OSError) as error:
        raise MemberSkippedError("fichier corrompu") from error
    return written
