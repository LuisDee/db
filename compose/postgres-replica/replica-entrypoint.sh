#!/bin/bash
# On first start (empty $PGDATA): wait for the primary, take a base
# backup with -R (writes standby.signal + primary_conninfo), then exec
# the standard postgres image entrypoint, which finds the already-
# populated data directory and starts postgres directly in standby mode
# -- it never runs initdb or docker-entrypoint-initdb.d for this path.
#
# On subsequent restarts (non-empty $PGDATA, e.g. `docker compose
# restart`), this block is skipped and we go straight to
# docker-entrypoint.sh, which just starts postgres against the existing
# standby data directory.
set -euo pipefail

: "${PRIMARY_HOST:=postgres}"
: "${PRIMARY_PORT:=5432}"
: "${REPLICATION_USER:=replicator}"
: "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD must be set (see compose/.env.example)}"

if [ -z "$(ls -A "$PGDATA" 2>/dev/null)" ]; then
    echo "replica-entrypoint: empty PGDATA, waiting for primary at ${PRIMARY_HOST}:${PRIMARY_PORT}..."
    until PGPASSWORD="$REPLICATION_PASSWORD" pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER" >/dev/null 2>&1; do
        sleep 2
    done

    echo "replica-entrypoint: primary is accepting connections, taking base backup"
    PGPASSWORD="$REPLICATION_PASSWORD" pg_basebackup \
        -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER" \
        -D "$PGDATA" -Fp -Xs -P -R
    chmod 700 "$PGDATA"
    echo "replica-entrypoint: base backup complete, standby.signal + primary_conninfo written"
fi

exec docker-entrypoint.sh postgres
