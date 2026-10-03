import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

BASE_URLS = {"demo": "https://demo.trading212.com", "live": "https://live.trading212.com"}
KEYCHAIN_SERVICE = "t212-mcp"
DEFAULT_CAPS = {"max_order_gbp": 1000, "max_daily_gbp": 2000}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    api_key: str
    api_secret: str
    cache_dir: Path
    log_path: Path
    trading_enabled: bool
    max_order_gbp: float
    max_daily_gbp: float

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]


def read_keychain(env: str, name: str) -> str | None:
    import keyring

    return keyring.get_password(KEYCHAIN_SERVICE, f"{env}_{name}")


def load_settings(environ: Mapping[str, str] = os.environ, keychain: Callable[[str, str], str | None] = read_keychain) -> Settings:
    env = environ.get("T212_ENV", "demo")
    if env not in BASE_URLS:
        raise ConfigError(f"T212_ENV must be one of {sorted(BASE_URLS)}, got {env!r}")

    def secret(name: str) -> str:
        variable = f"T212_{env.upper()}_{name.upper()}"
        if value := environ.get(variable) or keychain(env, name):
            return value
        raise ConfigError(f"Set {variable} or store '{env}_{name}' in the keychain under service '{KEYCHAIN_SERVICE}'")

    config_path = Path(environ.get("T212_CONFIG", Path.home() / ".config" / "t212-mcp" / "config.toml"))
    caps = DEFAULT_CAPS | (tomllib.loads(config_path.read_text()) if config_path.exists() else {})
    cache_dir = Path(environ.get("T212_CACHE_DIR", Path.home() / ".cache" / "t212-mcp"))
    log_path = Path(environ.get("T212_ORDER_LOG", Path.home() / ".local" / "state" / "t212-mcp" / f"orders-{env}.jsonl"))
    trading_enabled = env == "demo" or environ.get("T212_LIVE_TRADING") == "1"
    return Settings(env, secret("api_key"), secret("api_secret"), cache_dir, log_path, trading_enabled, caps["max_order_gbp"], caps["max_daily_gbp"])
