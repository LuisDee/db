#!/usr/bin/env python3
"""Seed QuestDB via its REST /exec endpoint.

QuestDB has no docker-entrypoint-initdb.d equivalent -- there is no
init-on-first-boot mechanism, unlike Postgres and Oracle. The documented
way to seed it is to run SQL against the REST API (port 9000) or PGWire
(port 8812) *after* the server reports healthy. This script does that
from the host (stdlib only, no dependencies), polling the REST endpoint
itself before seeding rather than trusting the container's Docker-level
healthcheck -- see compose/README.md's "what to check first" note on why
the questdb healthcheck itself is parse-only-verified in this
environment.

Creates a `metrics` time-series table (WAL, partitioned by day) and
seeds ~300k rows spread over the last ~30 days, with a denser burst in
the last 3 days to give a plausible accelerating-growth story for
tasks/playbooks/playbook-disk-space.md's table_storage()/
table_partitions() evidence queries.

Idempotent: re-running against an already-seeded instance skips the
bulk inserts if the table already has rows.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9000
SEED_ROW_THRESHOLD = 250_000  # below this, (re-)seed; at/above, skip

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS metrics (
    ts TIMESTAMP,
    host SYMBOL,
    metric SYMBOL,
    value DOUBLE
) TIMESTAMP(ts) PARTITION BY DAY WAL
"""

# ~200k rows spread over ~30 days (13s step) -- the historical baseline.
INSERT_BASELINE_SQL = """
INSERT INTO metrics
SELECT
    timestamp_sequence(dateadd('d', -30, now()), 13000000L) ts,
    rnd_symbol('questdb01', 'questdb02', 'questdb03') host,
    rnd_symbol('disk_used_pct', 'wal_lag', 'partition_count', 'row_count') metric,
    rnd_double() * 100 value
FROM long_sequence(200000)
"""

# ~100k rows crammed into the last 3 days (2.592s step) -- a growth
# spike right before "now", so a linear time-to-full read looks urgent.
INSERT_RECENT_BURST_SQL = """
INSERT INTO metrics
SELECT
    timestamp_sequence(dateadd('d', -3, now()), 2592000L) ts,
    rnd_symbol('questdb01', 'questdb02', 'questdb03') host,
    rnd_symbol('disk_used_pct', 'wal_lag', 'partition_count', 'row_count') metric,
    rnd_double() * 100 value
FROM long_sequence(100000)
"""


def exec_query(host: str, port: int, query: str, timeout: float = 30.0) -> dict:
    url = f"http://{host}:{port}/exec?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_ready(host: str, port: int, attempts: int = 30, delay: float = 2.0) -> None:
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            exec_query(host, port, "SELECT 1")
            return
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_err = exc
            time.sleep(delay)
    raise RuntimeError(f"questdb not reachable at {host}:{port} after {attempts} attempts") from last_err


def row_count(host: str, port: int) -> int:
    result = exec_query(host, port, "SELECT count() FROM metrics")
    return int(result["dataset"][0][0])


def seed(host: str, port: int) -> None:
    wait_ready(host, port)

    exec_query(host, port, CREATE_TABLE_SQL)

    try:
        existing = row_count(host, port)
    except Exception:
        existing = 0

    if existing >= SEED_ROW_THRESHOLD:
        print(f"questdb seed: metrics already has {existing} rows, skipping bulk insert")
        return

    print("questdb seed: inserting ~200k baseline rows over the last 30 days")
    exec_query(host, port, INSERT_BASELINE_SQL)
    print("questdb seed: inserting ~100k recent-burst rows over the last 3 days")
    exec_query(host, port, INSERT_RECENT_BURST_SQL)

    total = row_count(host, port)
    print(f"questdb seed: done, metrics has {total} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    seed(args.host, args.port)


if __name__ == "__main__":
    main()
