from pydantic import SecretStr

from app.config import ApiKeySettings


def _settings(value: str) -> ApiKeySettings:
    return ApiKeySettings(API_KEY_PEPPERS=SecretStr(value))


def test_keys_are_off_without_a_pepper():
    assert _settings("").enabled is False
    assert _settings("   ").enabled is False
    assert _settings("garbage-with-no-version").enabled is False


def test_the_first_pepper_is_the_one_new_keys_use():
    settings = _settings("v2=new-secret, v1=old-secret")

    assert settings.enabled is True
    assert settings.peppers == [("v2", "new-secret"), ("v1", "old-secret")]


def test_a_pepper_with_no_version_or_no_secret_is_left_out():
    assert _settings("v1=ok,=nothing,v3=,junk").peppers == [("v1", "ok")]


def test_a_secret_may_contain_an_equals_sign():
    assert _settings("v1=abc=def==").peppers == [("v1", "abc=def==")]


def test_the_peppers_are_not_in_the_representation_of_the_settings():
    assert "secret-value" not in repr(_settings("v1=secret-value"))
