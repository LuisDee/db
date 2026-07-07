-- Replication role used by the postgres-replica service (streaming
-- replication, for the future standby-replication-lag playbook: see
-- tasks/playbooks/playbook-replication-lag.md, which wants a live
-- Postgres streaming-replication pair to develop against).
--
-- Dev-only password, hardcoded here because docker-entrypoint-initdb.d
-- SQL files are not env-substituted. It must match REPLICATION_PASSWORD
-- in compose/.env (see compose/.env.example) and the value baked into
-- compose/postgres-replica/replica-entrypoint.sh's default. Not a real
-- secret -- local compose network only.
--
-- Idempotent: safe to re-run via `make seed` against an already-seeded
-- database.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'replicator') THEN
        CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'dev_only_replicator_pw';
    END IF;
END
$$;
