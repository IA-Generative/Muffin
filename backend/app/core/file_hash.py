import hashlib


def sha256_hex(data: bytes) -> str:
    """The hash that identifies a file's content (#300): what tells that the same file is added twice,
    and what another document reuses the results of."""
    return hashlib.sha256(data).hexdigest()
