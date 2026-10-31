"""The local provider of the secret store (#521): AES-256-GCM with a key ring."""

import base64

import pytest

from app.core.secret_store import (
    LocalProvider,
    SecretDecryptionError,
    SecretsNotConfiguredError,
)
from app.core.secret_store.local import parse_key_ring


def _key(seed: int) -> str:
    return base64.b64encode(bytes([seed]) * 32).decode()


def _provider(*ids: str) -> LocalProvider:
    return LocalProvider([(key_id, bytes([index + 1]) * 32) for index, key_id in enumerate(ids)])


async def test_a_secret_comes_back_as_it_went():
    provider = _provider("k1")

    ciphertext = await provider.encrypt("sk-the-key-of-a-service", context="row-1")

    assert await provider.decrypt(ciphertext, context="row-1") == "sk-the-key-of-a-service"


async def test_a_ciphertext_does_not_hold_the_secret_in_any_form():
    provider = _provider("k1")
    secret = "sk-the-key-of-a-service"

    ciphertext = await provider.encrypt(secret, context="row-1")

    assert secret not in ciphertext
    assert base64.b64encode(secret.encode()).decode() not in ciphertext
    assert ciphertext.startswith("local:k1:")


async def test_the_same_secret_is_never_encrypted_the_same_way_twice():
    provider = _provider("k1")

    first = await provider.encrypt("same", context="row-1")
    second = await provider.encrypt("same", context="row-1")

    assert first != second


async def test_a_ciphertext_opens_only_for_the_context_it_was_made_for():
    provider = _provider("k1")
    ciphertext = await provider.encrypt("secret", context="row-1|alice|transcription.api_key")

    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(ciphertext, context="row-2|alice|transcription.api_key")
    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(ciphertext, context="row-1|mallory|transcription.api_key")


async def test_a_ciphertext_that_was_altered_does_not_open():
    provider = _provider("k1")
    ciphertext = await provider.encrypt("secret", context="c")
    prefix, _, encoded = ciphertext.rpartition(":")
    raw = bytearray(base64.b64decode(encoded))
    raw[-1] ^= 1

    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(f"{prefix}:{base64.b64encode(bytes(raw)).decode()}", context="c")


@pytest.mark.parametrize(
    "ciphertext", ["", "garbage", "local:k1:", "local:k1:not base64!", "vault:v1:abc", "local:other:AAAA"]
)
async def test_what_is_not_a_ciphertext_of_this_provider_does_not_open(ciphertext):
    with pytest.raises(SecretDecryptionError):
        await _provider("k1").decrypt(ciphertext, context="c")


async def test_a_key_is_changed_without_losing_a_secret_while_the_old_one_stays_in_the_ring():
    old = _provider("k1")
    ciphertext = await old.encrypt("secret", context="c")
    ring = LocalProvider([("k2", bytes([9]) * 32), ("k1", bytes([1]) * 32)])

    assert await ring.decrypt(ciphertext, context="c") == "secret"
    assert (await ring.encrypt("new", context="c")).startswith("local:k2:")
    assert await ring.current_version() == "k2"

    without_old = LocalProvider([("k2", bytes([9]) * 32)])
    with pytest.raises(SecretDecryptionError):
        await without_old.decrypt(ciphertext, context="c")


async def test_a_rewrap_brings_a_secret_to_the_latest_key_and_keeps_it():
    ring = LocalProvider([("k2", bytes([9]) * 32), ("k1", bytes([1]) * 32)])
    ciphertext = await _provider("k1").encrypt("secret", context="c")
    assert ring.version_of(ciphertext) == "k1"

    rewrapped = await ring.rewrap(ciphertext, context="c")

    assert ring.version_of(rewrapped) == "k2"
    assert await ring.decrypt(rewrapped, context="c") == "secret"


def test_an_empty_ring_is_not_a_provider():
    with pytest.raises(SecretsNotConfiguredError):
        LocalProvider([])


def test_a_ring_is_read_from_id_and_base64_pairs_the_first_one_encrypting():
    assert [key_id for key_id, _ in parse_key_ring(f"k2={_key(2)}, k1={_key(1)}")] == ["k2", "k1"]
    assert parse_key_ring("") == []
    assert parse_key_ring("garbage,=,k=") == []


def test_a_key_that_is_not_base64_or_not_32_bytes_is_refused():
    with pytest.raises(SecretsNotConfiguredError):
        parse_key_ring("k1=not base64!")
    with pytest.raises(SecretsNotConfiguredError):
        parse_key_ring(f"k1={base64.b64encode(b'short').decode()}")


def test_the_error_for_a_bad_key_never_shows_the_key():
    secret = base64.b64encode(b"short").decode()

    with pytest.raises(SecretsNotConfiguredError) as error:
        parse_key_ring(f"k1={secret}")

    assert secret not in str(error.value)
