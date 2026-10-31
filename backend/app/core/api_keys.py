"""The personal API keys (#521, #513): how one is made, recognized and stored.

A key is `sk-muffin-` + 43 random base62 characters (256 bits) + a 6-character checksum of those. The checksum is
there for the tools that look for leaked secrets, and to turn away a mistyped or made-up key without a look at the
database - it protects nothing. What protects a key is that it is random and long, and that only `HMAC-SHA256(pepper,
key)` is stored: with nothing to guess, a slow hash (bcrypt, argon2) would only slow down each request."""

import hashlib
import hmac
import secrets
import zlib

PREFIX = "sk-muffin-"
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BODY_LENGTH = 43  # 62**43 > 2**256
_CHECKSUM_LENGTH = 6  # 62**6 > 2**32
# What of a key is shown to recognize it, after the prefix (never enough to use it).
VISIBLE_LENGTH = 6


def _base62(number: int, length: int) -> str:
    digits = []
    while number:
        number, rest = divmod(number, 62)
        digits.append(_ALPHABET[rest])
    return "".join(reversed(digits)).rjust(length, _ALPHABET[0])


def _checksum(body: str) -> str:
    return _base62(zlib.crc32(body.encode()), _CHECKSUM_LENGTH)


def generate_key() -> str:
    body = _base62(int.from_bytes(secrets.token_bytes(32)), _BODY_LENGTH)
    return f"{PREFIX}{body}{_checksum(body)}"


def visible_prefix(key: str) -> str:
    return key[: len(PREFIX) + VISIBLE_LENGTH]


def is_well_formed(token: str) -> bool:
    """Whether this is a key as `generate_key` makes them - which says nothing of whether it is one that exists."""
    if not token.startswith(PREFIX):
        return False
    rest = token[len(PREFIX) :]
    if len(rest) != _BODY_LENGTH + _CHECKSUM_LENGTH or any(char not in _ALPHABET for char in rest):
        return False
    body, checksum = rest[:_BODY_LENGTH], rest[_BODY_LENGTH:]
    return hmac.compare_digest(checksum, _checksum(body))


def hash_key(key: str, version: str, pepper: str) -> str:
    """`version$hex`: the version of the pepper says which one to check a key against."""
    digest = hmac.new(pepper.encode(), key.encode(), hashlib.sha256).hexdigest()
    return f"{version}${digest}"


def candidate_hashes(key: str, peppers: list[tuple[str, str]]) -> list[str]:
    """What a key would be stored as under each pepper in use: the one it was made with is not known beforehand."""
    return [hash_key(key, version, pepper) for version, pepper in peppers]
