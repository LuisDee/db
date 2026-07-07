"""Proves the executor against a real Postgres engine: read-only
enforcement is actually enforced by the server (not just app discipline),
and redaction actually strips a literal from real captured query text.

Deliberately does NOT use pg_stat_statements for the redaction proof --
verified empirically that Postgres normalizes literal constants into
$1/$2 placeholders in that view itself, so a redaction test against it
would pass whether or not redact_literals() ever ran. pg_stat_activity's
`query` column is genuinely unnormalized (it reflects the live/last
statement text as sent), which is what makes this proof honest.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from dba_agent.executor import PostgresRunner, run_playbook
from dba_agent.playbooks import Playbook, PlaybookQuery
from dba_agent.registry import Endpoint

pytestmark = pytest.mark.integration


def _endpoint_for(dsn: str) -> Endpoint:
    # postgres_dsn already carries its own user/password (needed to prove
    # connectivity in conftest.py); strip them back out here so the
    # executor's own _build_postgres_dsn appends the credential, exactly
    # as it will in production.
    os.environ["PG_TEST_RO_PASSWORD"] = "test"
    base = dsn.split(" user=")[0]
    return Endpoint(
        key="it-postgres",
        engine="postgres",
        dsn=base,
        credential_ref="PG_TEST_RO_PASSWORD",
        tier="dev",
    )


def test_read_only_enforced_by_the_server_not_just_app_code(postgres_dsn):
    # The dba_agent_ro role doesn't exist on this ad-hoc test instance --
    # proving true grant-based enforcement needs the real provisioning
    # SQL from docs/apply-path-security-model.md (a later task). What
    # *is* provable here, today: conn.read_only actually opens a
    # server-level READ ONLY transaction, so even a superuser connection
    # gets a write rejected by Postgres itself once inside one -- proving
    # the mechanism, independent of which role is subject to it.
    with psycopg.connect(postgres_dsn) as conn:
        conn.read_only = True
        with conn.cursor() as cur, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            cur.execute("INSERT INTO app.orders (customer_id, status, payload) VALUES (1, 'x', 'y')")


def test_evidence_bundle_redacts_a_real_captured_literal(postgres_dsn):
    # A held-open, autocommit connection's last statement stays visible
    # in pg_stat_activity.query -- genuinely unnormalized, unlike
    # pg_stat_statements (verified separately; see module docstring).
    held_conn = psycopg.connect(postgres_dsn, autocommit=True)
    held_conn.execute("SELECT customer_id FROM app.orders WHERE customer_id = 555444333")

    try:
        playbook = Playbook(
            key="it-check",
            queries={
                "postgres": (
                    PlaybookQuery(
                        name="active_queries",
                        sql=(
                            "SELECT query FROM pg_stat_activity "
                            "WHERE query ILIKE '%app.orders%555444333%' "
                            "AND pid != pg_backend_pid()"  # exclude this monitoring query's own row
                        ),
                        redact_columns=("query",),
                    ),
                )
            },
        )

        bundle = run_playbook(playbook, _endpoint_for(postgres_dsn), PostgresRunner())

        assert bundle.any_succeeded
        result = bundle.results[0]
        assert result.succeeded, result.error
        assert len(result.rows) > 0
        for row in result.rows:
            query_text = row[0]
            assert "555444333" not in query_text  # the literal must be gone
            assert "app.orders" in query_text  # the identifier must survive
    finally:
        held_conn.close()
