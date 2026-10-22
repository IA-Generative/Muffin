import hashlib
from typing import BinaryIO

_CHUNK_BYTES = 1024 * 1024


def sha256_hex(data: bytes) -> str:
    """The hash that identifies a file's content (#300): what tells that the same file is added twice,
    and what another document reuses the results of."""
    return hashlib.sha256(data).hexdigest()


def sha256_stream(fileobj: BinaryIO) -> tuple[str, int]:
    """sha256_hex of a file read chunk by chunk, never whole in memory, with its size - then back at
    its start, to be stored."""
    hasher, size = hashlib.sha256(), 0
    fileobj.seek(0)
    while chunk := fileobj.read(_CHUNK_BYTES):
        hasher.update(chunk)
        size += len(chunk)
    fileobj.seek(0)
    return hasher.hexdigest(), size
