# Streaming-replication standby of the `postgres` service. Plain
# postgres:16 with a custom entrypoint that takes a pg_basebackup from
# the primary on first start (empty PGDATA) and then hands off to the
# normal postgres entrypoint. No repmgr/patroni -- this is a POC-scale
# read replica to develop tasks/playbooks/playbook-replication-lag.md's
# Postgres query set against something real.
FROM postgres:16

COPY replica-entrypoint.sh /usr/local/bin/replica-entrypoint.sh
RUN chmod +x /usr/local/bin/replica-entrypoint.sh

ENTRYPOINT ["replica-entrypoint.sh"]
