from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_INIT_DIR = REPO_ROOT / "compose" / "postgres" / "init"


def _apply_sql_file(dsn: str, sql_path: Path) -> None:
    """Run a .sql file the same way postgres's own docker-entrypoint.sh
    does: shell out to psql. This is more faithful than re-implementing
    multi-statement execution over psycopg, and it's exactly what
    happens for real inside the postgres/postgres-replica containers.
    """
    result = subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"psql failed applying {sql_path.name}:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


def _wait_until_connectable(dsn: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_exc: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2):
                return
        except Exception as exc:  # noqa: BLE001 - retry on anything, report the last one
            last_exc = exc
            time.sleep(1)
    raise RuntimeError(f"postgres never became connectable at {dsn!r}: {last_exc}")


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """A real, connectable Postgres. Prefers POSTGRES_TEST_DSN (an
    already-running instance you point us at -- a local install, a dev
    box, whatever) over spinning a testcontainer, mirroring the
    oracle-schema-refresh repo's convention. Skips cleanly, with a
    reason, if neither is available -- never errors the whole suite.
    """
    override = os.environ.get("POSTGRES_TEST_DSN")
    if override:
        _wait_until_connectable(override, timeout=10)
        yield override
        return

    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError:
        pytest.skip("testcontainers not installed and POSTGRES_TEST_DSN not set")

    # DockerContainer(...) itself (not just .start()) talks to the docker
    # client on construction -- both must be inside the same try/except,
    # or a missing daemon raises instead of skipping cleanly.
    try:
        container = (
            DockerContainer("postgres:16")
            .with_env("POSTGRES_USER", "postgres")
            .with_env("POSTGRES_PASSWORD", "test")
            .with_env("POSTGRES_DB", "postgres")
            .with_exposed_ports(5432)
            # Mirrors compose.yaml's `command:` exactly -- shared_preload_libraries
            # cannot be set via ALTER SYSTEM/CREATE EXTENSION alone, it needs a
            # server restart, so it has to be a start-time flag here too.
            .with_command("postgres -c shared_preload_libraries=pg_stat_statements")
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - no daemon, no image pull, etc.
        pytest.skip(f"no Docker available for a postgres testcontainer: {exc}")

    try:
        wait_for_logs(container, "database system is ready to accept connections", timeout=60)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(5432)
        dsn = f"host={host} port={port} dbname=postgres user=postgres password=test"
        _wait_until_connectable(dsn, timeout=30)
        yield dsn
    finally:
        container.stop()


@pytest.fixture(scope="session")
def oracle_dsn():
    """Same contract as postgres_dsn, scaffolded for when this suite
    runs on a machine with Docker. Not provable in this sandbox: no
    realistic non-container way to run a real Oracle instance, and the
    testcontainers path needs a reachable daemon this environment
    doesn't have.
    """
    override = os.environ.get("ORACLE_TEST_DSN")
    if override:
        yield override
        return

    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError:
        pytest.skip("testcontainers not installed and ORACLE_TEST_DSN not set")

    try:
        container = (
            DockerContainer("gvenzl/oracle-free:23-slim")
            .with_env("ORACLE_PASSWORD", "test")
            .with_exposed_ports(1521)
            .with_volume_mapping(
                str(REPO_ROOT / "compose" / "oracle" / "init"),
                "/container-entrypoint-initdb.d",
                mode="ro",
            )
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - no daemon reachable in this sandbox
        pytest.skip(f"no Docker available for an oracle-free testcontainer: {exc}")

    try:
        wait_for_logs(container, "DATABASE IS READY TO USE", timeout=180)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1521)
        yield f"{host}:{port}/FREEPDB1"
    finally:
        container.stop()


@pytest.fixture(scope="session")
def questdb_host_port() -> tuple[str, int]:
    """Same contract again, for QuestDB. Not provable in this sandbox
    either: no Docker daemon, and downloading QuestDB's standalone
    binary is blocked by this environment's egress allowlist (confirmed
    403 -- questdb.io isn't on the proxy's allowed-hosts list).

    Yields (host, port) rather than a URL to match compose/questdb/
    seed.py's actual function signatures (exec_query/seed take host and
    port separately).
    """
    override = os.environ.get("QUESTDB_TEST_DSN")
    if override:
        host, _, port = override.partition(":")
        yield host, int(port)
        return

    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError:
        pytest.skip("testcontainers not installed and QUESTDB_TEST_DSN not set")

    try:
        container = DockerContainer("questdb/questdb").with_exposed_ports(9000)
        container.start()
    except Exception as exc:  # noqa: BLE001 - no daemon reachable in this sandbox
        pytest.skip(f"no Docker available for a questdb testcontainer: {exc}")

    try:
        wait_for_logs(container, "server-main enjoy", timeout=60)
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(9000))
        yield host, port
    finally:
        container.stop()
