import pytest

from t212_mcp.config import ConfigError, TradingRules, load_settings


DEMO_KEYS = {"T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"}


def no_keychain(env, name):
    return None


@pytest.fixture
def load(tmp_path):
    def load_with(environ, keychain=no_keychain):
        return load_settings({"T212_CONFIG": str(tmp_path / "missing.toml"), **environ}, keychain=keychain)
    return load_with


def test_defaults_to_demo(load):
    settings = load(DEMO_KEYS)
    assert (settings.env, settings.base_url, settings.api_key, settings.api_secret) == ("demo", "https://demo.trading212.com", "k", "s")


def test_live_uses_live_keys(load):
    environ = {"T212_ENV": "live", "T212_DEMO_API_KEY": "dk", "T212_DEMO_API_SECRET": "ds", "T212_LIVE_API_KEY": "lk", "T212_LIVE_API_SECRET": "ls"}
    settings = load(environ)
    assert (settings.base_url, settings.api_key, settings.api_secret) == ("https://live.trading212.com", "lk", "ls")


def test_falls_back_to_keychain(load):
    settings = load({}, keychain=lambda env, name: f"{env}-{name}")
    assert (settings.api_key, settings.api_secret) == ("demo-api_key", "demo-api_secret")


def test_missing_secret_names_the_variable(load):
    with pytest.raises(ConfigError, match="T212_DEMO_API_SECRET"):
        load({"T212_DEMO_API_KEY": "k"})


def test_rejects_unknown_env(load):
    with pytest.raises(ConfigError, match="T212_ENV"):
        load({"T212_ENV": "prod"})


def test_live_trading_is_off_by_default(tmp_path, load):
    settings = load({"T212_ENV": "live", "T212_LIVE_API_KEY": "k", "T212_LIVE_API_SECRET": "s"})
    assert settings.rules == TradingRules(enabled=False, max_order_gbp=1000, max_daily_gbp=2000)


def test_live_trading_switch(load):
    settings = load({"T212_ENV": "live", "T212_LIVE_TRADING": "1", "T212_LIVE_API_KEY": "k", "T212_LIVE_API_SECRET": "s"})
    assert settings.rules.enabled is True


def test_demo_always_trades(load):
    assert load(DEMO_KEYS).rules.enabled is True


def test_caps_from_config_file(tmp_path, load):
    config = tmp_path / "config.toml"
    config.write_text("max_order_gbp = 250\nmax_daily_gbp = 500\n")
    settings = load({"T212_CONFIG": str(config), "T212_DEMO_API_KEY": "k", "T212_DEMO_API_SECRET": "s"})
    assert (settings.rules.max_order_gbp, settings.rules.max_daily_gbp) == (250, 500)


@pytest.mark.parametrize(("text", "message"), [("max_order_gbp = ", "not valid TOML"), ("max_order = 5", "unknown settings"), ("max_daily_gbp = -1", "positive number"), ("max_order_gbp = \"lots\"", "positive number"), ("max_order_gbp = nan", "positive number"), ("max_daily_gbp = inf", "positive number")])
def test_bad_config_file(tmp_path, text, message, load):
    config = tmp_path / "config.toml"
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load({"T212_CONFIG": str(config), **DEMO_KEYS})
