"""Which provider the secret store uses, and what makes the application refuse to start (#521)."""

import base64

import pytest
from pydantic import SecretStr

from app.config import SecretsSettings
from app.core.secret_store import (
    LocalProvider,
    SecretsNotConfiguredError,
    VaultTransitProvider,
    build_provider,
    check_configuration,
)

KEY = base64.b64encode(bytes([7]) * 32).decode()


def _settings(**overrides) -> SecretsSettings:
    values = {"SECRETS_PROVIDER": "local", "SECRETS_LOCAL_KEYS": SecretStr(f"k1={KEY}")} | overrides
    return SecretsSettings(**values)


def test_the_local_provider_is_built_from_the_key_ring():
    assert isinstance(build_provider(_settings()), LocalProvider)


def test_the_vault_provider_is_built_from_its_address():
    provider = build_provider(_settings(SECRETS_PROVIDER="vault", VAULT_ADDR="http://vault:8200"))

    assert isinstance(provider, VaultTransitProvider)


def test_requiring_vault_forbids_any_other_provider():
    with pytest.raises(SecretsNotConfiguredError):
        build_provider(_settings(SECRETS_REQUIRE_VAULT=True))
    with pytest.raises(SecretsNotConfiguredError):
        check_configuration(_settings(SECRETS_REQUIRE_VAULT=True))


def test_requiring_vault_is_met_by_vault():
    check_configuration(_settings(SECRETS_REQUIRE_VAULT=True, SECRETS_PROVIDER="vault", VAULT_ADDR="http://vault:8200"))


def test_vault_without_an_address_does_not_start():
    with pytest.raises(SecretsNotConfiguredError):
        check_configuration(_settings(SECRETS_PROVIDER="vault"))
    with pytest.raises(SecretsNotConfiguredError):
        build_provider(_settings(SECRETS_PROVIDER="vault"))


def test_an_unknown_provider_does_not_start():
    with pytest.raises(SecretsNotConfiguredError):
        check_configuration(_settings(SECRETS_PROVIDER="somewhere"))
    with pytest.raises(SecretsNotConfiguredError):
        build_provider(_settings(SECRETS_PROVIDER="somewhere"))


def test_a_bad_local_key_does_not_start():
    with pytest.raises(SecretsNotConfiguredError):
        check_configuration(_settings(SECRETS_LOCAL_KEYS=SecretStr("k1=short")))


def test_no_key_at_all_is_allowed_but_nothing_can_be_stored():
    settings = _settings(SECRETS_LOCAL_KEYS=SecretStr(""))

    check_configuration(settings)
    with pytest.raises(SecretsNotConfiguredError):
        build_provider(settings)


def test_the_keys_are_not_in_the_representation_of_the_settings():
    assert KEY not in repr(_settings())
    assert "root-token-value" not in repr(_settings(VAULT_TOKEN=SecretStr("root-token-value")))


async def test_the_application_does_not_start_when_it_requires_vault_and_has_none(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "SecretsSettings", lambda: _settings(SECRETS_REQUIRE_VAULT=True))

    with pytest.raises(SecretsNotConfiguredError):
        async with main.lifespan(main.app):
            pytest.fail("the application started")
