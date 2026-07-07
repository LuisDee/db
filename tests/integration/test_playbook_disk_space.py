"""Proves tasks/playbooks/playbook-disk-space.md's actual shipped
content -- playbooks/filesystem-disk-space.yaml -- against real engines,
not a hand-built stand-in playbook. Same discipline
test_full_chain_wiring.py established for the generic registry/
playbook/executor chain; this proves *this* playbook's queries actually
run and return the seeded disk-growth story
(compose/postgres/init/03_schema_seed.sql's app.event_log,
compose/questdb/seed.py's metrics table) is really there.

Postgres: live-verified in this sandbox against the real local server
(see tests/integration/conftest.py's postgres_dsn fixture and this
repo's own CLAUDE.md-equivalent setup notes). QuestDB: structurally
identical test shape, but skips cleanly here -- no Docker, and
QuestDB's standalone binary download is blocked by this sandbox's
egress policy (matches tests/integration/test_questdb_seed.py's
existing, already-accepted skip).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dba_agent.executor import PostgresRunner, QuestDBRunner, run_playbook
from dba_agent.playbooks import load_playbook
from dba_agent.registry import Endpoint

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK_PATH = REPO_ROOT / "playbooks" / "filesystem-disk-space.yaml"


def _postgres_endpoint(dsn: str) -> Endpoint:
    # dsn from the fixture carries its own user/password (needed for the
    # fixture's own connectivity check); strip that back out so the
    # registry-shaped dsn (host/port/db only) is what actually reaches
    # PostgresRunner, and it appends dba_agent_ro + the resolved
    # credential itself -- exactly the real code path.
    os.environ["DISK_SPACE_IT_PG_CRED"] = "test"
    base_dsn = dsn.split(" user=")[0]
    return Endpoint(
        key="it-disk-space-postgres",
        engine="postgres",
        dsn=base_dsn,
        credential_ref="DISK_SPACE_IT_PG_CRED",
        tier="dev",
    )


def test_playbook_file_loads_and_has_expected_shape():
    playbook = load_playbook(PLAYBOOK_PATH)

    assert playbook.key == "filesystem-disk-space"
    postgres_names = [q.name for q in playbook.queries_for("postgres")]
    assert postgres_names == ["database_size", "largest_relations", "wal_summary"]
    questdb_names = [q.name for q in playbook.queries_for("questdb")]
    assert questdb_names == ["table_storage_summary", "metrics_partitions"]
    assert playbook.queries_for("oracle") == ()  # deliberately out of scope


def test_postgres_queries_return_real_evidence_from_the_seeded_database(postgres_dsn):
    playbook = load_playbook(PLAYBOOK_PATH)
    endpoint = _postgres_endpoint(postgres_dsn)

    bundle = run_playbook(playbook, endpoint, PostgresRunner())

    assert bundle.playbook_key == "filesystem-disk-space"
    assert len(bundle.results) == 3
    assert bundle.any_succeeded

    by_name = {r.query_name: r for r in bundle.results}
    for result in by_name.values():
        assert result.succeeded, result.error

    size_result = by_name["database_size"]
    assert size_result.columns == ("size_bytes", "size_pretty")
    (size_bytes, size_pretty) = size_result.rows[0]
    assert size_bytes > 0
    assert isinstance(size_pretty, str)

    relations_result = by_name["largest_relations"]
    relation_names = {(row[0], row[1]) for row in relations_result.rows}
    # the compose seed's own two tables -- the disk-growth story this
    # playbook exists to surface -- must actually show up.
    assert ("app", "event_log") in relation_names
    assert ("app", "orders") in relation_names
    for row in relations_result.rows:
        total_bytes = row[2]
        assert total_bytes > 0

    wal_result = by_name["wal_summary"]
    (wal_file_count, wal_total_bytes, wal_total_pretty) = wal_result.rows[0]
    assert wal_file_count > 0
    assert wal_total_bytes > 0


def _questdb_endpoint(host: str, port: int) -> Endpoint:
    return Endpoint(
        key="it-disk-space-questdb",
        engine="questdb",
        dsn=f"{host}:{port}",
        credential_ref="DISK_SPACE_IT_QUESTDB_CRED",  # unused by QuestDBRunner, required by the schema
        tier="dev",
    )


def test_questdb_queries_return_real_evidence_from_the_seeded_metrics_table(questdb_host_port):
    # Mirrors test_questdb_seed.py's own pattern: real seed, real engine,
    # skips cleanly (via the questdb_host_port fixture) when neither
    # Docker nor QUESTDB_TEST_DSN is available -- true in this sandbox.
    from compose.questdb.seed import seed

    host, port = questdb_host_port
    seed(host, port)

    playbook = load_playbook(PLAYBOOK_PATH)
    endpoint = _questdb_endpoint(host, port)

    bundle = run_playbook(playbook, endpoint, QuestDBRunner())

    assert len(bundle.results) == 2
    by_name = {r.query_name: r for r in bundle.results}
    for result in by_name.values():
        assert result.succeeded, result.error

    storage = by_name["table_storage_summary"]
    table_names = [row[0] for row in storage.rows]
    assert "metrics" in table_names

    partitions = by_name["metrics_partitions"]
    assert len(partitions.rows) > 0
    total_rows = sum(row[2] for row in partitions.rows)  # numRows column
    assert total_rows > 250_000  # matches test_questdb_seed.py's own seeded-row assertion
