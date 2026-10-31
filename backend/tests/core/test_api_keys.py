"""How a personal API key is made, recognized and hashed (#521)."""

import pytest

from app.core.api_keys import (
    PREFIX,
    VISIBLE_LENGTH,
    candidate_hashes,
    generate_key,
    hash_key,
    is_well_formed,
    visible_prefix,
)


def test_a_key_has_a_prefix_a_long_random_body_and_a_checksum():
    key = generate_key()

    assert key.startswith("sk-muffin-")
    assert len(key) == len(PREFIX) + 43 + 6
    assert key[len(PREFIX) :].isalnum()


def test_keys_are_never_the_same():
    assert len({generate_key() for _ in range(200)}) == 200


def test_a_key_that_was_made_is_well_formed():
    assert all(is_well_formed(generate_key()) for _ in range(50))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "sk-muffin-",
        "sk-other-" + "a" * 49,
        "Bearer abc",
        "a" * 59,
    ],
)
def test_what_is_not_a_key_is_not_well_formed(token):
    assert is_well_formed(token) is False


def test_a_key_with_one_character_changed_fails_its_checksum():
    key = generate_key()
    changed = key[: len(PREFIX)] + ("A" if key[len(PREFIX)] != "A" else "B") + key[len(PREFIX) + 1 :]

    assert is_well_formed(changed) is False


def test_a_key_cut_short_or_extended_is_not_well_formed():
    key = generate_key()

    assert is_well_formed(key[:-1]) is False
    assert is_well_formed(key + "a") is False


def test_a_key_with_a_character_outside_the_alphabet_is_not_well_formed():
    key = generate_key()

    assert is_well_formed(key[:-1] + "-") is False
    assert is_well_formed(key[:-1] + " ") is False


def test_what_is_shown_of_a_key_is_never_enough_to_use_it():
    key = generate_key()

    assert visible_prefix(key) == key[: len(PREFIX) + VISIBLE_LENGTH]
    assert len(visible_prefix(key)) < len(key) // 2


def test_a_key_is_stored_as_the_version_of_the_pepper_and_an_hmac():
    key = generate_key()

    stored = hash_key(key, "v1", "pepper")

    assert stored.startswith("v1$")
    assert len(stored) == 3 + 64
    assert key not in stored
    assert hash_key(key, "v1", "pepper") == stored


def test_another_pepper_or_another_key_gives_another_hash():
    key = generate_key()

    assert hash_key(key, "v1", "pepper") != hash_key(key, "v1", "other pepper")
    assert hash_key(key, "v1", "pepper") != hash_key(generate_key(), "v1", "pepper")


def test_a_key_is_looked_up_under_each_pepper_in_use():
    key = generate_key()

    hashes = candidate_hashes(key, [("v2", "new"), ("v1", "old")])

    assert hashes == [hash_key(key, "v2", "new"), hash_key(key, "v1", "old")]
