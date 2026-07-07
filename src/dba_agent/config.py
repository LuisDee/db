from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

_REQUIRED_ENV_SECRETS = ("ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AppConfig:
    environment: str
    log_level: str
    anthropic_api_key: str
    slack_bot_token: str

    def secrets(self) -> tuple[str, ...]:
        return (self.anthropic_api_key, self.slack_bot_token)

    def __repr__(self) -> str:
        return (
            f"AppConfig(environment={self.environment!r}, log_level={self.log_level!r}, "
            "anthropic_api_key=<redacted>, slack_bot_token=<redacted>)"
        )


def load_config(yaml_path=None, env: dict | None = None) -> AppConfig:
    env = env if env is not None else os.environ

    missing = [name for name in _REQUIRED_ENV_SECRETS if not env.get(name)]
    if missing:
        raise ConfigError(f"missing required secret env var(s): {', '.join(missing)}")

    settings: dict = {}
    if yaml_path is not None:
        if not yaml_path.exists():
            raise ConfigError(f"config file not found: {yaml_path}")
        loaded = yaml.safe_load(yaml_path.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"config file must contain a YAML mapping: {yaml_path}")
        settings = loaded

    return AppConfig(
        environment=settings.get("environment", "development"),
        log_level=settings.get("log_level", "INFO"),
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        slack_bot_token=env["SLACK_BOT_TOKEN"],
    )
