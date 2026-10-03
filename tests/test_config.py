import pytest

from t212_mcp.config import ConfigError, TradingRules, load_settings


DEMO_KEYS = {"T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"}


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


def test_live_trading_is_off_by_default(tmp_path):
    settings = load_settings({"T212_CONFIG": str(tmp_path / "missing.toml"), "T212_ENV": "live", "T212_LIVE_API_KEY": "k", "T212_LIVE_API_SECRET": "s"}, keychain=no_keychain)
    assert settings.rules == TradingRules(enabled=False, max_order_gbp=1000, max_daily_gbp=2000)


def test_live_trading_switch():
    settings = load_settings({"T212_ENV": "live", "T212_LIVE_TRADING": "1", "T212_LIVE_API_KEY": "k", "T212_LIVE_API_SECRET": "s"}, keychain=no_keychain)
    assert settings.rules.enabled is True


def test_demo_always_trades():
    assert load_settings({"T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"}, keychain=no_keychain).rules.enabled is True


def test_caps_from_config_file(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("max_order_gbp = 250\nmax_daily_gbp = 500\n")
    settings = load_settings({"T212_CONFIG": str(config), "T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"}, keychain=no_keychain)
    assert (settings.rules.max_order_gbp, settings.rules.max_daily_gbp) == (250, 500)


@pytest.mark.parametrize(("text", "message"), [("max_order_gbp = ", "not valid TOML"), ("max_order = 5", "unknown settings"), ("max_daily_gbp = -1", "positive number"), ("max_order_gbp = \"lots\"", "positive number")])
def test_bad_config_file(tmp_path, text, message):
    config = tmp_path / "config.toml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_settings({"T212_CONFIG": str(config), **DEMO_KEYS}, keychain=no_keychain)
