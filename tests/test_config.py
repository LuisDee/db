from pathlib import Path

import pytest

from dba_agent.config import ConfigError, load_config


def test_missing_secret_env_raises():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config(env={"SLACK_BOT_TOKEN": "xoxb-test"})


def test_loads_defaults_with_only_env_secrets():
    config = load_config(env={"ANTHROPIC_API_KEY": "sk-test", "SLACK_BOT_TOKEN": "xoxb-test"})
    assert config.environment == "development"
    assert config.log_level == "INFO"
    assert config.anthropic_api_key == "sk-test"
    assert config.slack_bot_token == "xoxb-test"


def test_loads_yaml_overrides(tmp_path: Path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("environment: staging\nlog_level: DEBUG\n")

    config = load_config(
        yaml_path=yaml_path,
        env={"ANTHROPIC_API_KEY": "sk-test", "SLACK_BOT_TOKEN": "xoxb-test"},
    )

    assert config.environment == "staging"
    assert config.log_level == "DEBUG"


def test_missing_yaml_file_raises(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(
            yaml_path=tmp_path / "nope.yaml",
            env={"ANTHROPIC_API_KEY": "sk-test", "SLACK_BOT_TOKEN": "xoxb-test"},
        )


def test_non_mapping_yaml_raises(tmp_path: Path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("- just\n- a\n- list\n")

    with pytest.raises(ConfigError, match="mapping"):
        load_config(
            yaml_path=yaml_path,
            env={"ANTHROPIC_API_KEY": "sk-test", "SLACK_BOT_TOKEN": "xoxb-test"},
        )


def test_repr_does_not_leak_secrets():
    config = load_config(
        env={"ANTHROPIC_API_KEY": "sk-super-secret", "SLACK_BOT_TOKEN": "xoxb-super-secret"}
    )

    rendered = repr(config)

    assert "sk-super-secret" not in rendered
    assert "xoxb-super-secret" not in rendered


def test_secrets_helper_returns_both_values_for_masking():
    config = load_config(env={"ANTHROPIC_API_KEY": "sk-test", "SLACK_BOT_TOKEN": "xoxb-test"})
    assert config.secrets() == ("sk-test", "xoxb-test")
