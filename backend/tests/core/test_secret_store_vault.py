"""The Vault Transit provider of the secret store (#521): against a Vault of development, and against a stand-in for
the cases a real one will not produce on demand (it down, it sealed, a token that no longer is)."""

import base64
import json
import os
import uuid

import httpx
import pytest
from pydantic import SecretStr

from app.config import SecretsSettings
from app.core.secret_store import (
    SecretDecryptionError,
    SecretsNotConfiguredError,
    SecretUnavailableError,
    VaultTransitProvider,
)

ADDR = os.environ.get("VAULT_TEST_ADDR", "")
TOKEN = os.environ.get("VAULT_TEST_TOKEN", "test-root-token")


def _settings(**overrides) -> SecretsSettings:
    values = {
        "SECRETS_PROVIDER": "vault",
        "VAULT_ADDR": ADDR or "http://vault.test",
        "VAULT_AUTH_METHOD": "token",
        "VAULT_TOKEN": SecretStr(TOKEN),
    }
    return SecretsSettings(**(values | overrides))


# --- a real Vault ---


@pytest.fixture
async def vault():
    """A Vault in development mode, with Transit on and a key of our own, `derived` as the key of Muffin must be."""
    if not ADDR:
        pytest.skip("VAULT_TEST_ADDR is not set")
    name = f"muffin-test-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(base_url=ADDR, headers={"X-Vault-Token": TOKEN}, timeout=5) as http:
        try:
            await http.post("/v1/sys/mounts/transit", json={"type": "transit"})
        except httpx.HTTPError:
            if os.environ.get("CI"):
                pytest.fail(f"The Vault of the tests at {ADDR} cannot be reached")
            pytest.skip(f"No Vault at {ADDR}: docker compose -f docker-compose-test.yaml up -d vault-test")
        created = await http.post(f"/v1/transit/keys/{name}", json={"derived": True})
        assert created.status_code in (200, 204), created.text
        provider = VaultTransitProvider(_settings(VAULT_TRANSIT_KEY=name))
        yield provider, http, name
        await provider.aclose()
        await http.post(f"/v1/transit/keys/{name}/config", json={"deletion_allowed": True})
        await http.delete(f"/v1/transit/keys/{name}")


async def test_a_secret_goes_through_vault_and_comes_back(vault):
    provider, _, _ = vault

    ciphertext = await provider.encrypt("sk-the-key-of-a-service", context="row-1|alice|x")

    assert ciphertext.startswith("vault:v1:")
    assert "sk-the-key-of-a-service" not in ciphertext
    assert await provider.decrypt(ciphertext, context="row-1|alice|x") == "sk-the-key-of-a-service"


async def test_a_secret_with_accents_and_symbols_comes_back_as_it_went(vault):
    provider, _, _ = vault
    secret = 'clé-d\'été ✓ "quotes" \\ \n and more'

    assert await provider.decrypt(await provider.encrypt(secret, context="c"), context="c") == secret


async def test_the_same_secret_is_not_encrypted_the_same_way_twice(vault):
    provider, _, _ = vault

    assert await provider.encrypt("same", context="c") != await provider.encrypt("same", context="c")


async def test_a_ciphertext_opens_only_for_the_context_it_was_made_for(vault):
    provider, _, _ = vault
    ciphertext = await provider.encrypt("secret", context="row-1|alice|x")

    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(ciphertext, context="row-2|alice|x")
    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(ciphertext, context="row-1|mallory|x")


async def test_a_ciphertext_that_is_not_one_does_not_open(vault):
    provider, _, _ = vault

    with pytest.raises(SecretDecryptionError):
        await provider.decrypt("vault:v1:not-a-ciphertext", context="c")


async def test_after_a_rotation_old_secrets_still_open_and_a_rewrap_moves_them_without_showing_them(vault):
    provider, http, name = vault
    old = await provider.encrypt("secret", context="c")
    assert provider.version_of(old) == "v1"
    assert (await http.post(f"/v1/transit/keys/{name}/rotate")).status_code in (200, 204)
    provider._version = None  # the provider looks the version up again, as it does after a minute

    assert await provider.current_version() == "v2"
    assert await provider.decrypt(old, context="c") == "secret"
    rewrapped = await provider.rewrap(old, context="c")
    assert provider.version_of(rewrapped) == "v2"
    assert await provider.decrypt(rewrapped, context="c") == "secret"


async def test_once_old_versions_are_disabled_only_rewrapped_secrets_open(vault):
    provider, http, name = vault
    old = await provider.encrypt("secret", context="c")
    await http.post(f"/v1/transit/keys/{name}/rotate")
    rewrapped = await provider.rewrap(old, context="c")
    await http.post(f"/v1/transit/keys/{name}/config", json={"min_decryption_version": 2})

    assert await provider.decrypt(rewrapped, context="c") == "secret"
    with pytest.raises(SecretDecryptionError):
        await provider.decrypt(old, context="c")


async def test_a_wrong_token_is_a_provider_that_is_not_available_not_a_ciphertext_that_does_not_open(vault):
    _, _, name = vault
    provider = VaultTransitProvider(_settings(VAULT_TRANSIT_KEY=name, VAULT_TOKEN=SecretStr("not-a-token")))

    with pytest.raises(SecretUnavailableError):
        await provider.encrypt("secret", context="c")
    await provider.aclose()


async def test_the_store_rotates_and_rewraps_secrets_in_the_database_through_vault(vault):
    from sqlalchemy import delete

    from app.db import async_session_factory
    from app.models.stored_secret import StoredSecret
    from app.services.secret_store_service import SecretStore

    provider, http, name = vault
    async with async_session_factory() as db:
        store = SecretStore(db, provider)
        rows = [
            await store.put(owner="alice", purpose="transcription.api_key", plaintext=f"sk-secret-{n}", created_by="a")
            for n in range(3)
        ]
        await db.commit()
        ids = [row.id for row in rows]
        assert await store.versions() == {"v1": 3}

        await http.post(f"/v1/transit/keys/{name}/rotate")
        provider._version = None
        progress = await store.rewrap_batch(limit=2)
        await db.commit()
        assert (progress.rewrapped, progress.remaining, progress.current_version) == (2, 1, "v2")
        progress = await store.rewrap_batch(limit=2)
        await db.commit()
        assert (progress.rewrapped, progress.remaining) == (1, 0)
        assert await store.versions() == {"v2": 3}

        await http.post(f"/v1/transit/keys/{name}/config", json={"min_decryption_version": 2})
        for n, secret_id in enumerate(ids):
            assert await store.reveal(secret_id, owner="alice", purpose="transcription.api_key") == f"sk-secret-{n}"
        await db.execute(delete(StoredSecret))
        await db.commit()


async def _limited_provider(http, name: str) -> tuple[VaultTransitProvider, str]:
    """A provider with the token the application is given in production: it may encrypt, decrypt and rewrap with its key
    (`update` on those three paths) and nothing else - not `create`, which would make Transit invent a key, not even
    read it."""
    policy = "\n".join(
        f'path "transit/{operation}/{name}" {{ capabilities = ["update"] }}'
        for operation in ("encrypt", "decrypt", "rewrap")
    )
    assert (await http.put(f"/v1/sys/policies/acl/{name}", json={"policy": policy})).status_code in (200, 204)
    token = (await http.post("/v1/auth/token/create", json={"policies": [name], "ttl": "1h"})).json()["auth"][
        "client_token"
    ]
    return VaultTransitProvider(_settings(VAULT_TRANSIT_KEY=name, VAULT_TOKEN=SecretStr(token))), token


async def test_the_minimal_policy_of_the_application_is_enough_to_encrypt_decrypt_and_rewrap(vault):
    _, http, name = vault
    provider, _ = await _limited_provider(http, name)

    ciphertext = await provider.encrypt("secret", context="c")
    assert await provider.decrypt(ciphertext, context="c") == "secret"
    assert provider.version_of(await provider.rewrap(ciphertext, context="c")) == "v1"
    assert await provider.current_version() == "v1"
    await provider.aclose()


async def test_the_application_cannot_read_rotate_or_delete_its_key(vault):
    _, http, name = vault
    _, token = await _limited_provider(http, name)

    async with httpx.AsyncClient(base_url=ADDR, headers={"X-Vault-Token": token}, timeout=5) as app:
        assert (await app.get(f"/v1/transit/keys/{name}")).status_code == 403
        assert (await app.post(f"/v1/transit/keys/{name}/rotate")).status_code == 403
        assert (await app.delete(f"/v1/transit/keys/{name}")).status_code == 403
        assert (await app.get(f"/v1/transit/export/encryption-key/{name}")).status_code == 403


async def test_a_key_that_does_not_exist_is_not_available_and_is_not_made_up(vault):
    _, http, name = vault
    other = f"{name}-absent"
    provider, token = await _limited_provider(http, other)

    with pytest.raises(SecretUnavailableError):
        await provider.encrypt("secret", context="c")

    assert (await http.get(f"/v1/transit/keys/{other}")).status_code == 404
    await provider.aclose()


# --- a stand-in for Vault ---


class Standin:
    """A Vault that answers what it is told to, and keeps what it was asked."""

    def __init__(self, handler) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://vault.test")


def _ok(ciphertext: str = "vault:v3:abc") -> httpx.Response:
    return httpx.Response(200, json={"data": {"ciphertext": ciphertext}})


async def test_the_secret_and_the_context_are_sent_in_base64_with_the_token_and_the_namespace():
    standin = Standin(lambda request: _ok())
    provider = VaultTransitProvider(
        _settings(VAULT_NAMESPACE="team-a", VAULT_TRANSIT_MOUNT="tr", VAULT_TRANSIT_KEY="k"), standin.client()
    )

    await provider.encrypt("secret é", context="row|owner|purpose")

    [request] = standin.requests
    assert request.url.path == "/v1/tr/encrypt/k"
    assert request.headers["X-Vault-Token"] == TOKEN
    assert request.headers["X-Vault-Namespace"] == "team-a"
    body = json.loads(request.content)
    assert base64.b64decode(body["plaintext"]).decode() == "secret é"
    assert base64.b64decode(body["context"]).decode() == "row|owner|purpose"


async def test_vault_that_cannot_be_reached_is_not_available():
    def refuse(request):
        raise httpx.ConnectError("refused")

    provider = VaultTransitProvider(_settings(), Standin(refuse).client())

    with pytest.raises(SecretUnavailableError):
        await provider.encrypt("secret", context="c")
    with pytest.raises(SecretUnavailableError):
        await provider.decrypt("vault:v1:x", context="c")


async def test_a_vault_that_is_sealed_or_in_error_is_not_available_and_the_secret_is_not_in_the_error():
    standin = Standin(lambda request: httpx.Response(503, json={"errors": ["Vault is sealed"]}))
    provider = VaultTransitProvider(_settings(), standin.client())

    with pytest.raises(SecretUnavailableError) as error:
        await provider.encrypt("the-secret-itself", context="c")

    assert "the-secret-itself" not in str(error.value)


async def test_a_ciphertext_vault_refuses_with_a_400_does_not_open():
    standin = Standin(lambda request: httpx.Response(400, json={"errors": ["cipher: message authentication failed"]}))
    provider = VaultTransitProvider(_settings(), standin.client())

    with pytest.raises(SecretDecryptionError):
        await provider.decrypt("vault:v1:x", context="c")


async def test_the_version_of_the_key_is_read_once_in_a_while_not_at_every_call():
    standin = Standin(lambda request: _ok("vault:v7:abc"))
    provider = VaultTransitProvider(_settings(), standin.client())

    assert await provider.current_version() == "v7"
    assert await provider.current_version() == "v7"

    assert len(standin.requests) == 1


def test_the_version_of_a_ciphertext_is_read_from_it():
    assert VaultTransitProvider.version_of("vault:v12:abcdef") == "v12"
    assert VaultTransitProvider.version_of("garbage") == ""


async def test_with_a_token_method_and_no_token_nothing_is_tried():
    standin = Standin(lambda request: _ok())
    provider = VaultTransitProvider(_settings(VAULT_TOKEN=SecretStr("")), standin.client())

    with pytest.raises(SecretsNotConfiguredError):
        await provider.encrypt("secret", context="c")

    assert standin.requests == []


def test_without_an_address_there_is_no_provider():
    with pytest.raises(SecretsNotConfiguredError):
        VaultTransitProvider(SecretsSettings(SECRETS_PROVIDER="vault", VAULT_ADDR=""))


# --- logging in with the service account of the pod ---


def _kubernetes(tmp_path, **overrides) -> SecretsSettings:
    jwt = tmp_path / "token"
    jwt.write_text("the-service-account-jwt\n")
    values = {"VAULT_AUTH_METHOD": "kubernetes", "VAULT_K8S_JWT_PATH": str(jwt), "VAULT_K8S_ROLE": "muffin"}
    return _settings(**(values | overrides))


async def test_the_pod_logs_in_with_its_service_account_and_uses_the_token_vault_gives(tmp_path):
    logins = []

    def handler(request):
        if request.url.path == "/v1/auth/kubernetes/login":
            logins.append(json.loads(request.content))
            return httpx.Response(200, json={"auth": {"client_token": "short-token", "lease_duration": 3600}})
        return _ok()

    standin = Standin(handler)
    provider = VaultTransitProvider(_kubernetes(tmp_path), standin.client())

    await provider.encrypt("a", context="c")
    await provider.encrypt("b", context="c")

    assert logins == [{"role": "muffin", "jwt": "the-service-account-jwt"}]  # once, not for each call
    calls = [r for r in standin.requests if "encrypt" in r.url.path]
    assert [r.headers["X-Vault-Token"] for r in calls] == ["short-token", "short-token"]


async def test_a_token_vault_no_longer_knows_is_replaced_by_one_new_login_and_the_call_goes_through(tmp_path):
    tokens = iter(["first-token", "second-token"])
    seen = []

    def handler(request):
        if request.url.path.startswith("/v1/auth/"):
            return httpx.Response(200, json={"auth": {"client_token": next(tokens), "lease_duration": 3600}})
        seen.append(request.headers["X-Vault-Token"])
        return httpx.Response(403, json={"errors": ["permission denied"]}) if len(seen) == 1 else _ok()

    provider = VaultTransitProvider(_kubernetes(tmp_path), Standin(handler).client())

    assert await provider.encrypt("secret", context="c") == "vault:v3:abc"
    assert seen == ["first-token", "second-token"]


async def test_a_token_that_is_refused_even_after_a_new_login_is_not_tried_again(tmp_path):
    def handler(request):
        if request.url.path.startswith("/v1/auth/"):
            return httpx.Response(200, json={"auth": {"client_token": "t", "lease_duration": 3600}})
        return httpx.Response(403, json={"errors": ["permission denied"]})

    standin = Standin(handler)
    provider = VaultTransitProvider(_kubernetes(tmp_path), standin.client())

    with pytest.raises(SecretUnavailableError):
        await provider.encrypt("secret", context="c")

    assert len([r for r in standin.requests if r.url.path.startswith("/v1/auth/")]) == 2


async def test_a_login_vault_refuses_is_not_available(tmp_path):
    standin = Standin(lambda request: httpx.Response(403, json={"errors": ["role not found"]}))
    provider = VaultTransitProvider(_kubernetes(tmp_path), standin.client())

    with pytest.raises(SecretUnavailableError):
        await provider.encrypt("secret", context="c")


async def test_without_the_token_of_the_service_account_nothing_is_tried(tmp_path):
    standin = Standin(lambda request: _ok())
    provider = VaultTransitProvider(
        _kubernetes(tmp_path, VAULT_K8S_JWT_PATH=str(tmp_path / "missing")), standin.client()
    )

    with pytest.raises(SecretsNotConfiguredError):
        await provider.encrypt("secret", context="c")

    assert standin.requests == []
