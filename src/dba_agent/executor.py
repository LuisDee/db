from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from dba_agent.playbooks import Playbook, PlaybookQuery
from dba_agent.redact import redact_literals
from dba_agent.registry import Endpoint

# The read-only identity is the same role name on every target database
# (spec §6: dba_agent_ro) -- the registry's dsn field carries host/port/
# database only, never a username, so this is the one place it's filled in.
READ_ONLY_USER = "dba_agent_ro"

DEFAULT_QUERY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class QueryResult:
    query_name: str
    sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...] | None
    error: str | None
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class EvidenceBundle:
    playbook_key: str
    endpoint_key: str
    results: tuple[QueryResult, ...]

    @property
    def any_succeeded(self) -> bool:
        return any(r.succeeded for r in self.results)


class EngineRunner(Protocol):
    def run(
        self, endpoint: Endpoint, query: PlaybookQuery, timeout_seconds: float
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
        """Execute one query read-only; return (columns, rows)."""
        ...


def _redact_row(row: tuple[Any, ...], columns: tuple[str, ...], redact_columns: tuple[str, ...]) -> tuple[Any, ...]:
    if not redact_columns:
        return row
    redact_indexes = {columns.index(name) for name in redact_columns if name in columns}
    if not redact_indexes:
        return row
    return tuple(
        redact_literals(value) if i in redact_indexes and isinstance(value, str) else value
        for i, value in enumerate(row)
    )


def run_playbook(
    playbook: Playbook,
    endpoint: Endpoint,
    runner: EngineRunner,
    timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
) -> EvidenceBundle:
    results: list[QueryResult] = []
    for query in playbook.queries_for(endpoint.engine):
        start = time.monotonic()
        try:
            columns, rows = runner.run(endpoint, query, timeout_seconds)
            redacted_rows = tuple(_redact_row(row, columns, query.redact_columns) for row in rows)
            results.append(
                QueryResult(
                    query_name=query.name,
                    sql=query.sql,
                    columns=columns,
                    rows=redacted_rows,
                    error=None,
                    duration_seconds=time.monotonic() - start,
                )
            )
        except Exception as exc:  # noqa: BLE001 - partial failure is tolerated by design
            results.append(
                QueryResult(
                    query_name=query.name,
                    sql=query.sql,
                    columns=(),
                    rows=None,
                    error=str(exc),
                    duration_seconds=time.monotonic() - start,
                )
            )
    return EvidenceBundle(playbook_key=playbook.key, endpoint_key=endpoint.key, results=tuple(results))


# --- Postgres -----------------------------------------------------------
#
# SQL/DSN construction kept as pure functions (unit-tested directly, no
# DB needed) separate from the actual socket I/O (integration-tested
# against a real engine in tests/integration/) -- the same split the
# sibling oracle-schema-refresh repo's own conventions call for.


def _build_postgres_dsn(endpoint: Endpoint, password: str) -> str:
    return f"{endpoint.dsn} user={READ_ONLY_USER} password={password}"


def _statement_timeout_sql(timeout_seconds: float) -> str:
    return f"SET statement_timeout = {int(timeout_seconds * 1000)}"


class PostgresRunner:
    def run(self, endpoint: Endpoint, query: PlaybookQuery, timeout_seconds: float):
        import psycopg

        dsn = _build_postgres_dsn(endpoint, endpoint.resolve_credential())
        try:
            conn = psycopg.connect(dsn)
        except Exception as exc:
            # A connection failure's exception message must never become
            # a vector for `dsn` (which embeds the resolved password) to
            # leak into QueryResult.error and from there into synthesis
            # prompts, Jira drafts, and Slack messages -- all of which
            # sit outside logging_setup.py's SecretMaskingFilter (that
            # filter only covers the dba_agent logger, not values passed
            # in-band through return values/exceptions). Verified
            # empirically that psycopg's own error text does not include
            # the password, but relying on that holding across driver
            # versions/error paths forever is fragile -- fail safe.
            raise RuntimeError(
                f"connection to postgres endpoint {endpoint.key!r} failed"
            ) from exc

        with conn:
            # Defence in depth (spec: "connections opened read-only where
            # the driver supports it") -- the real enforcement is that
            # dba_agent_ro has no write grants at all; this just makes a
            # accidental write fail at the transaction layer too.
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(_statement_timeout_sql(timeout_seconds))
                cur.execute(query.sql)
                columns = tuple(d.name for d in cur.description) if cur.description else ()
                rows = tuple(tuple(row) for row in cur.fetchall())
        return columns, rows


# --- Oracle ---------------------------------------------------------------
#
# Unverified against a live instance in this sandbox (no Docker; see
# tasks/foundation/integration-test-infra.md) -- structurally ready to
# prove for real via tests/integration/test_oracle_seed.py's fixture.


def _build_oracle_dsn(endpoint: Endpoint) -> str:
    return endpoint.dsn  # already host:port/service_name, per compose/registry.yaml's convention


class OracleRunner:
    def run(self, endpoint: Endpoint, query: PlaybookQuery, timeout_seconds: float):
        import oracledb

        with oracledb.connect(
            dsn=_build_oracle_dsn(endpoint),
            user=READ_ONLY_USER,
            password=endpoint.resolve_credential(),
        ) as conn:
            conn.call_timeout = int(timeout_seconds * 1000)
            try:
                # Best-effort defence in depth, same rationale as Postgres's
                # conn.read_only above -- real enforcement is grant-based
                # (dba_agent_ro has no write privileges). Must be the first
                # statement in a transaction; tolerated if it isn't (e.g. a
                # pooled/reused session), never fatal to the actual query.
                conn.cursor().execute("SET TRANSACTION READ ONLY")
            except oracledb.Error:
                pass
            cur = conn.cursor()
            cur.execute(query.sql)
            columns = tuple(d[0] for d in cur.description) if cur.description else ()
            rows = tuple(tuple(row) for row in cur.fetchall())
        return columns, rows


# --- QuestDB ----------------------------------------------------------------
#
# REST /exec is stateless per-call -- there's no persistent read-only
# transaction concept to opt into here; defence in depth is grant-based
# only. Deliberately not importing compose/questdb/seed.py's exec_query:
# compose/ is throwaway demo tooling that depends on src/, not the other
# way around.


def _questdb_exec_url(endpoint: Endpoint, sql: str) -> str:
    host, _, port = endpoint.dsn.partition(":")
    return f"http://{host}:{port}/exec?" + urllib.parse.urlencode({"query": sql})


class QuestDBRunner:
    def run(self, endpoint: Endpoint, query: PlaybookQuery, timeout_seconds: float):
        url = _questdb_exec_url(endpoint, query.sql)
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"questdb query failed: {exc.read().decode('utf-8', 'replace')}") from exc

        columns = tuple(col["name"] for col in payload.get("columns", []))
        rows = tuple(tuple(row) for row in payload.get("dataset", []))
        return columns, rows
