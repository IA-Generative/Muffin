"""The secret store (#521): what is kept of a secret, who gets it back, and what follows a rotation of the key."""

import uuid

import pytest
from loguru import logger
from sqlalchemy import delete, select, update

from app.core.secret_store import LocalProvider, SecretDecryptionError
from app.db import async_session_factory
from app.models.stored_secret import StoredSecret
from app.services.secret_store_service import InvalidPurposeError, SecretNotFoundError, SecretStore

SECRET = "sk-a-long-key-of-a-service-1234567890"
PURPOSE = "transcription.api_key"


def _provider(*ids: str) -> LocalProvider:
    return LocalProvider([(key_id, bytes([index + 1]) * 32) for index, key_id in enumerate(ids)])


@pytest.fixture
async def db():
    async with async_session_factory() as session:
        yield session
    async with async_session_factory() as session:
        await session.execute(delete(StoredSecret))
        await session.commit()


@pytest.fixture
def logs():
    lines: list[str] = []
    handler = logger.add(lambda message: lines.append(str(message)), level="DEBUG")
    yield lines
    logger.remove(handler)


async def _put(db, provider=None, owner: str | None = "alice", plaintext: str = SECRET) -> StoredSecret:
    store = SecretStore(db, provider or _provider("k1"))
    row = await store.put(owner=owner, purpose=PURPOSE, plaintext=plaintext, created_by="admin")
    await db.commit()
    return row


async def test_a_secret_is_stored_encrypted_and_comes_back_for_its_owner_and_purpose(db):
    provider = _provider("k1")
    row = await _put(db, provider)

    assert await SecretStore(db, provider).reveal(row.id, owner="alice", purpose=PURPOSE) == SECRET


async def test_the_secret_is_in_no_column_of_the_database(db):
    row = await _put(db)

    async with async_session_factory() as session:
        stored = (await session.execute(select(StoredSecret).where(StoredSecret.id == row.id))).scalar_one()
    everything = " ".join(str(value) for value in vars(stored).values())
    assert SECRET not in everything
    assert SECRET[:20] not in everything
    assert stored.ciphertext.startswith("local:k1:")
    assert stored.key_version == "k1"


async def test_only_the_last_characters_of_a_long_secret_are_kept_to_tell_it_apart(db):
    row = await _put(db)
    short = await _put(db, plaintext="short")

    assert row.hint == SECRET[-4:]
    assert short.hint == ""


async def test_an_owner_or_a_purpose_that_is_not_the_rows_finds_nothing(db):
    provider = _provider("k1")
    row = await _put(db, provider)
    store = SecretStore(db, provider)

    with pytest.raises(SecretNotFoundError):
        await store.reveal(row.id, owner="mallory", purpose=PURPOSE)
    with pytest.raises(SecretNotFoundError):
        await store.reveal(row.id, owner=None, purpose=PURPOSE)
    with pytest.raises(SecretNotFoundError):
        await store.reveal(row.id, owner="alice", purpose="another.purpose")
    with pytest.raises(SecretNotFoundError):
        await store.reveal(uuid.uuid4(), owner="alice", purpose=PURPOSE)


async def test_a_secret_of_the_deployment_has_no_owner_and_is_not_a_users(db):
    provider = _provider("k1")
    row = await _put(db, provider, owner=None)
    store = SecretStore(db, provider)

    assert await store.reveal(row.id, owner=None, purpose=PURPOSE) == SECRET
    with pytest.raises(SecretNotFoundError):
        await store.reveal(row.id, owner="alice", purpose=PURPOSE)


async def test_a_ciphertext_copied_to_another_row_does_not_open_there(db):
    """Someone with write access to the database moves alice's secret to a row of mallory's: it must not open."""
    provider = _provider("k1")
    alices = await _put(db, provider, owner="alice")
    malorys = await _put(db, provider, owner="mallory", plaintext="mallory-own-secret-value")
    malorys_id, alices_ciphertext = malorys.id, alices.ciphertext
    async with async_session_factory() as session:
        await session.execute(
            update(StoredSecret).where(StoredSecret.id == malorys_id).values(ciphertext=alices_ciphertext)
        )
        await session.commit()
    db.expire_all()  # this session loaded the rows before the other one changed one

    with pytest.raises(SecretDecryptionError):
        await SecretStore(db, provider).reveal(malorys_id, owner="mallory", purpose=PURPOSE)


async def test_a_purpose_that_is_not_a_plain_name_is_refused(db):
    store = SecretStore(db, _provider("k1"))

    for purpose in ["", "Has Spaces", "UPPER", "../etc", "a" * 101, "x|y"]:
        with pytest.raises(InvalidPurposeError):
            await store.put(owner="alice", purpose=purpose, plaintext="s", created_by="admin")


async def test_a_secret_is_replaced_in_place_and_the_old_value_is_gone(db):
    provider = _provider("k1")
    row = await _put(db, provider)
    store = SecretStore(db, provider)

    await store.replace(row.id, "sk-a-new-key-of-the-service-9876543210", owner="alice", purpose=PURPOSE)
    await db.commit()

    assert await store.reveal(row.id, owner="alice", purpose=PURPOSE) == "sk-a-new-key-of-the-service-9876543210"
    refreshed = await store.get(row.id, owner="alice", purpose=PURPOSE)
    assert refreshed.hint == "3210" and refreshed.rotated_at is not None


async def test_a_secret_is_deleted_and_is_then_not_found(db):
    provider = _provider("k1")
    row = await _put(db, provider)
    store = SecretStore(db, provider)

    await store.delete(row.id, owner="alice", purpose=PURPOSE)
    await db.commit()

    with pytest.raises(SecretNotFoundError):
        await store.reveal(row.id, owner="alice", purpose=PURPOSE)
    with pytest.raises(SecretNotFoundError):
        await store.delete(row.id, owner="alice", purpose=PURPOSE)


async def test_a_use_is_noted_but_not_written_again_within_a_minute(db):
    provider = _provider("k1")
    row = await _put(db, provider)
    store = SecretStore(db, provider)
    await store.reveal(row.id, owner="alice", purpose=PURPOSE)
    async with async_session_factory() as session:
        first = (await session.execute(select(StoredSecret.last_accessed_at))).scalar_one()
    assert first is not None

    await store.reveal(row.id, owner="alice", purpose=PURPOSE)

    async with async_session_factory() as session:
        assert (await session.execute(select(StoredSecret.last_accessed_at))).scalar_one() == first


# --- a rotation of the key ---


async def test_after_a_rotation_the_secrets_are_rewrapped_a_batch_at_a_time_and_stay_readable(db):
    old = _provider("k1")
    rows = [await _put(db, old, plaintext=f"{SECRET}-{index}") for index in range(5)]
    rotated = LocalProvider([("k2", bytes([9]) * 32), ("k1", bytes([1]) * 32)])
    store = SecretStore(db, rotated)
    assert await store.versions() == {"k1": 5}

    first = await store.rewrap_batch(limit=3)
    await db.commit()
    assert (first.rewrapped, first.remaining, first.current_version) == (3, 2, "k2")
    assert await store.versions() == {"k1": 2, "k2": 3}

    second = await store.rewrap_batch(limit=3)
    await db.commit()
    assert (second.rewrapped, second.remaining) == (2, 0)
    assert await store.versions() == {"k2": 5}

    # The old key can leave the ring: nothing depends on it any more.
    only_new = SecretStore(db, LocalProvider([("k2", bytes([9]) * 32)]))
    for index, row in enumerate(rows):
        assert await only_new.reveal(row.id, owner="alice", purpose=PURPOSE) == f"{SECRET}-{index}"


async def test_a_rewrap_with_nothing_to_do_does_nothing(db):
    await _put(db)

    progress = await SecretStore(db, _provider("k1")).rewrap_batch()

    assert (progress.rewrapped, progress.remaining) == (0, 0)


# --- nothing leaks ---


async def test_the_secret_is_in_no_log_whatever_is_done_with_it(db, logs):
    provider = _provider("k1")
    row = await _put(db, provider)
    store = SecretStore(db, provider)
    await store.reveal(row.id, owner="alice", purpose=PURPOSE)
    await store.replace(row.id, "sk-a-new-key-of-the-service-9876543210", owner="alice", purpose=PURPOSE)
    await store.delete(row.id, owner="alice", purpose=PURPOSE)

    text = "\n".join(logs)
    assert SECRET not in text and "sk-a-new-key" not in text
    assert str(row.id) in text  # who and what are logged, which is the point


async def test_the_error_for_a_secret_that_does_not_open_does_not_show_it(db):
    provider = _provider("k1")
    row = await _put(db, provider)

    with pytest.raises(SecretDecryptionError) as error:
        await SecretStore(db, _provider("other")).reveal(row.id, owner="alice", purpose=PURPOSE)

    assert SECRET not in str(error.value) and row.ciphertext not in str(error.value)
