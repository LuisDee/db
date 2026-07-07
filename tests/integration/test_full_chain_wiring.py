"""Proves the actual glue between tasks, not hand-built stand-ins.

Every other test either exercises one task's own loader/executor with
fixture objects, or hand-constructs an Endpoint/Playbook directly in
test code. Neither proves that a real registry.yaml, loaded through
load_registry(), produces an Endpoint whose .dsn is actually what
PostgresRunner expects -- or that a real playbook.yaml, loaded through
load_playbook(), actually feeds run_playbook() correctly. This is that
missing link: registry file -> load_registry() -> resolve() -> playbook
file -> load_playbook() -> run_playbook() -> a real evidence bundle,
using only the public loader functions each task actually ships,
against the real seeded schema from compose/postgres/init/.
"""

from __future__ import annotations

import os

import pytest

from dba_agent.executor import PostgresRunner, run_playbook
from dba_agent.playbooks import load_playbook
from dba_agent.registry import load_registry

pytestmark = pytest.mark.integration

REGISTRY_YAML = """
wiring-smoke-postgres:
  engine: postgres
  dsn: "{dsn}"
  credential_ref: WIRING_SMOKE_TEST_CRED
  tier: dev
  aliases: [smoke-test-db]
"""

PLAYBOOK_YAML = """
name: wiring-smoke-test
notes: |
  Not a real playbook -- proves the registry/playbook/executor chain
  actually links together, using the same seeded schema
  compose/postgres/init/03_schema_seed.sql already ships. Real playbook
  content lives in tasks/playbooks/playbook-disk-space.md etc.
engine_queries:
  postgres:
    - name: order_count
      sql: "SELECT count(*) FROM app.orders"
    - name: event_log_count
      sql: "SELECT count(*) FROM app.event_log"
"""


def test_registry_file_to_evidence_bundle_end_to_end(postgres_dsn, tmp_path):
    # postgres_dsn already carries its own user/password (needed by
    # conftest.py to prove connectivity); strip them back out so the
    # registry's dsn field matches what a real registry entry would
    # actually store (host/port/db only -- credentials are always
    # resolved separately, never embedded in the registry file).
    base_dsn = postgres_dsn.split(" user=")[0]
    os.environ["WIRING_SMOKE_TEST_CRED"] = "test"

    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(REGISTRY_YAML.format(dsn=base_dsn))
    playbook_path = tmp_path / "playbook.yaml"
    playbook_path.write_text(PLAYBOOK_YAML)

    # This is the actual chain: real loader functions, real endpoint
    # resolution (by alias, not just top-level key -- proves that path
    # too), real executor, real database.
    registry = load_registry(registry_path)
    endpoint = registry.resolve("smoke-test-db")  # via alias, not the top-level key
    playbook = load_playbook(playbook_path)

    bundle = run_playbook(playbook, endpoint, PostgresRunner())

    assert bundle.playbook_key == "wiring-smoke-test"
    assert bundle.endpoint_key == "wiring-smoke-postgres"
    assert bundle.any_succeeded
    assert len(bundle.results) == 2

    order_count = next(r for r in bundle.results if r.query_name == "order_count")
    event_log_count = next(r for r in bundle.results if r.query_name == "event_log_count")
    assert order_count.succeeded, order_count.error
    assert event_log_count.succeeded, event_log_count.error
    assert order_count.rows[0][0] > 0  # the compose seed script's actual data
    assert event_log_count.rows[0][0] > 0
