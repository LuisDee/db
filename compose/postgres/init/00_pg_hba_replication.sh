#!/bin/bash
# Allow the postgres-replica container to open a physical replication
# connection. The official postgres image's default pg_hba.conf allows
# "all" databases for "all" users, but per Postgres's own pg_hba.conf
# semantics the "all" database keyword does NOT match replication
# connections -- only the literal "replication" keyword does. Without
# this line, pg_basebackup / streaming replication from postgres-replica
# fails at the pg_hba layer even though the role and password are correct.
#
# Runs once, at first-boot init (docker-entrypoint-initdb.d scripts only
# run against an empty $PGDATA). The entrypoint restarts postgres as PID 1
# after all init scripts finish, so this takes effect on the same start.
set -euo pipefail

echo "host replication ${REPLICATION_USER:-replicator} all scram-sha-256" >> "$PGDATA/pg_hba.conf"
