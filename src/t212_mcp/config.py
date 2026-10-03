import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

Environment = Literal["demo", "live"]
BASE_URLS: dict[Environment, str] = {"demo": "https://demo.trading212.com", "live": "https://live.trading212.com"}
KEYCHAIN_SERVICE = "t212-mcp"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class TradingRules:
    enabled: bool = False
    max_order_gbp: float = 1000
    max_daily_gbp: float = 2000


CAP_NAMES = {"max_order_gbp", "max_daily_gbp"}


@dataclass(frozen=True)
class Settings:
    env: Environment
    api_key: str
    api_secret: str
    cache_dir: Path
    log_path: Path
    rules: TradingRules

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]


def read_keychain(env: str, name: str) -> str | None:
    import keyring

    return keyring.get_password(KEYCHAIN_SERVICE, f"{env}_{name}")


def read_caps(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        caps = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} is not valid TOML: {error}") from error
    if unknown := set(caps) - CAP_NAMES:
        raise ConfigError(f"{path} has unknown settings {sorted(unknown)}; allowed: {sorted(CAP_NAMES)}")
    for name, value in caps.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ConfigError(f"{path}: {name} must be a positive number, got {value!r}")
    return caps


def load_settings(environ: Mapping[str, str] = os.environ, keychain: Callable[[str, str], str | None] = read_keychain) -> Settings:
    env = environ.get("T212_ENV", "demo")
    if env not in get_args(Environment):
        raise ConfigError(f"T212_ENV must be one of {list(get_args(Environment))}, got {env!r}")

    def secret(name: str) -> str:
        variable = f"T212_{env.upper()}_{name.upper()}"
        if value := environ.get(variable) or keychain(env, name):
            return value
        raise ConfigError(f"Set {variable} or store '{env}_{name}' in the keychain under service '{KEYCHAIN_SERVICE}'")

    config_path = Path(environ.get("T212_CONFIG", Path.home() / ".config" / "t212-mcp" / "config.toml"))
    rules = TradingRules(enabled=env == "demo" or environ.get("T212_LIVE_TRADING") == "1", **read_caps(config_path))
    return Settings(
        env=env,
        api_key=secret("api_key"),
        api_secret=secret("api_secret"),
        cache_dir=Path(environ.get("T212_CACHE_DIR", Path.home() / ".cache" / "t212-mcp")),
        log_path=Path(environ.get("T212_ORDER_LOG", Path.home() / ".local" / "state" / "t212-mcp" / f"orders-{env}.jsonl")),
        rules=rules,
    )
