from dba_agent.logging_setup import configure_logging


def test_secret_is_redacted_from_log_output(capsys):
    logger = configure_logging("INFO", secrets=["sk-super-secret"])
    logger.info("connecting with key %s", "sk-super-secret")

    output = capsys.readouterr().out

    assert "sk-super-secret" not in output
    assert "REDACTED" in output


def test_non_secret_messages_pass_through_unchanged(capsys):
    logger = configure_logging("INFO", secrets=["sk-super-secret"])
    logger.info("agent started")

    output = capsys.readouterr().out

    assert "agent started" in output


def test_empty_secret_values_are_never_matched(capsys):
    logger = configure_logging("INFO", secrets=["", None])
    logger.info("hello world")

    output = capsys.readouterr().out

    assert "hello world" in output
