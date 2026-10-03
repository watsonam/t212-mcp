import pytest

from t212_mcp.config import ConfigError, load_settings


def no_keychain(env, name):
    return None


def test_defaults_to_demo():
    settings = load_settings({"T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"}, keychain=no_keychain)
    assert (settings.env, settings.base_url, settings.api_key, settings.api_secret) == ("demo", "https://demo.trading212.com", "k", "s")


def test_live_uses_live_keys():
    environ = {"T212_ENV": "live", "T212_DEMO_API_KEY": "dk", "T212_DEMO_API_SECRET": "ds", "T212_LIVE_API_KEY": "lk", "T212_LIVE_API_SECRET": "ls"}
    settings = load_settings(environ, keychain=no_keychain)
    assert (settings.base_url, settings.api_key, settings.api_secret) == ("https://live.trading212.com", "lk", "ls")


def test_falls_back_to_keychain():
    settings = load_settings({}, keychain=lambda env, name: f"{env}-{name}")
    assert (settings.api_key, settings.api_secret) == ("demo-api_key", "demo-api_secret")


def test_missing_secret_names_the_variable():
    with pytest.raises(ConfigError, match="T212_DEMO_API_SECRET"):
        load_settings({"T212_DEMO_API_KEY": "k"}, keychain=no_keychain)


def test_rejects_unknown_env():
    with pytest.raises(ConfigError, match="T212_ENV"):
        load_settings({"T212_ENV": "prod"}, keychain=no_keychain)
