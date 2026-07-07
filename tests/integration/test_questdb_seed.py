"""Proves compose/questdb/seed.py against a real QuestDB instance.

Not provable in this sandbox: no Docker daemon, and downloading
QuestDB's standalone (non-container) distribution is blocked by this
environment's egress allowlist (confirmed: 403 from download.questdb.io,
not on the proxy's allowed-hosts list). Runs for real the moment this
suite executes on a machine with Docker.
"""

from __future__ import annotations

import pytest

from compose.questdb.seed import exec_query, row_count, seed

pytestmark = pytest.mark.integration


def test_metrics_table_seeded(questdb_host_port):
    host, port = questdb_host_port
    seed(host, port)

    assert row_count(host, port) > 250_000

    # Re-running must be a no-op, not duplicate rows -- this is the
    # idempotency `make seed` depends on for re-runs.
    count_before = row_count(host, port)
    seed(host, port)
    assert row_count(host, port) == count_before


def test_metrics_has_recent_burst(questdb_host_port):
    host, port = questdb_host_port
    seed(host, port)

    result = exec_query(
        host, port, "SELECT count() FROM metrics WHERE ts > dateadd('d', -3, now())"
    )
    (recent_count,) = result["dataset"][0]
    assert recent_count > 0
