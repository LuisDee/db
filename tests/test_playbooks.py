from pathlib import Path

import pytest

from dba_agent.playbooks import PlaybookError, load_playbook

FIXTURES = Path(__file__).parent / "fixtures"


def test_loads_valid_playbook():
    playbook = load_playbook(FIXTURES / "playbook-example.yaml")

    assert playbook.key == "example-playbook"
    assert len(playbook.queries_for("postgres")) == 2
    assert playbook.queries_for("postgres")[0].name == "row_count"
    assert playbook.queries_for("postgres")[0].sql == "SELECT count(*) FROM app.orders"


def test_queries_for_unknown_engine_is_empty_not_an_error():
    playbook = load_playbook(FIXTURES / "playbook-example.yaml")
    assert playbook.queries_for("questdb") == ()


def test_redact_columns_parsed():
    playbook = load_playbook(FIXTURES / "playbook-example.yaml")
    recent_queries = playbook.queries_for("postgres")[1]
    assert recent_queries.redact_columns == ("query",)


def test_query_without_redact_columns_defaults_to_empty():
    playbook = load_playbook(FIXTURES / "playbook-example.yaml")
    row_count = playbook.queries_for("postgres")[0]
    assert row_count.redact_columns == ()


def test_missing_file_raises():
    with pytest.raises(PlaybookError, match="not found"):
        load_playbook(FIXTURES / "does-not-exist.yaml")


def test_missing_name_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("engine_queries: {}\n")
    with pytest.raises(PlaybookError, match="name"):
        load_playbook(bad)


def test_non_mapping_engine_queries_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad\nengine_queries: not-a-mapping\n")
    with pytest.raises(PlaybookError, match="mapping"):
        load_playbook(bad)


def test_malformed_query_entry_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad\nengine_queries:\n  postgres:\n    - {sql: 'SELECT 1'}\n")
    with pytest.raises(PlaybookError, match="malformed"):
        load_playbook(bad)


def test_forbidden_write_keyword_rejected_at_load_time():
    with pytest.raises(PlaybookError, match="forbidden keyword"):
        load_playbook(FIXTURES / "playbook-forbidden-keyword.yaml")
