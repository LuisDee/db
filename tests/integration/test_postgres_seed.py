"""Proves compose/postgres/init/*.sql against a real Postgres engine.

This is the thing no unit test can show: that the actual SQL shipped in
the compose stack runs cleanly end-to-end, and that pg_stat_statements
(which needs a server restart to enable, not just CREATE EXTENSION)
really does populate for a real query.
"""

from __future__ import annotations

import psycopg
import pytest

from conftest import POSTGRES_INIT_DIR, _apply_sql_file

pytestmark = pytest.mark.integration

INIT_SQL_FILES = sorted(POSTGRES_INIT_DIR.glob("*.sql"))


def test_init_sql_files_exist():
    # Guards against a silent rename/deletion making the rest of this
    # module vacuously pass over zero files.
    names = {f.name for f in INIT_SQL_FILES}
    assert names == {"01_replication_role.sql", "02_extensions.sql", "03_schema_seed.sql"}


def test_all_init_sql_files_apply_cleanly(postgres_dsn):
    for sql_file in INIT_SQL_FILES:
        _apply_sql_file(postgres_dsn, sql_file)  # raises with psql's stderr on failure

    # Idempotency check: every file in compose/ claims to be safe to
    # re-run (that's what `make seed` relies on) -- prove it, don't
    # just take the comment's word for it.
    for sql_file in INIT_SQL_FILES:
        _apply_sql_file(postgres_dsn, sql_file)


def test_replication_role_created(postgres_dsn):
    with psycopg.connect(postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'replicator'")
        assert cur.fetchone() is not None


def test_seeded_schema_present_with_expected_shape(postgres_dsn):
    with psycopg.connect(postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.orders")
        (orders_count,) = cur.fetchone()
        assert orders_count > 0

        cur.execute("SELECT count(*) FROM app.event_log")
        (event_log_count,) = cur.fetchone()
        assert event_log_count > 0

        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'app' AND tablename = 'orders' AND indexname != 'orders_pkey'"
        )
        # The deliberate absence of this index is the point (see
        # 03_schema_seed.sql's own comment) -- assert the gap, not just
        # the table.
        assert cur.fetchall() == []


def test_pg_stat_statements_extension_loaded_and_populated(postgres_dsn):
    with psycopg.connect(postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'pg_stat_statements'")
        if cur.fetchone() is None:
            pytest.skip(
                "pg_stat_statements extension not present -- this DSN's instance wasn't "
                "started with shared_preload_libraries=pg_stat_statements (required at "
                "server start, not settable via CREATE EXTENSION alone). Testcontainers "
                "path sets this; a POSTGRES_TEST_DSN override instance must set it itself."
            )

        # Generate a real query, then confirm pg_stat_statements actually
        # captured it -- proves the whole preload+extension chain, not
        # just that the catalog entry exists.
        cur.execute("SELECT customer_id, status FROM app.orders WHERE customer_id = 12345")
        cur.fetchall()

        cur.execute(
            "SELECT count(*) FROM pg_stat_statements WHERE query ILIKE '%FROM app.orders%'"
        )
        (matching,) = cur.fetchone()
        assert matching > 0
