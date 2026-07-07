-- Seed schema for the DBA agent compose stack.
--
-- Two tables, deliberately shaped to support two future playbooks:
--
--  * app.orders    -- no index on the columns a typical lookup query
--                     filters on. Gives pg_stat_statements a real slow
--                     query to surface (missing-index / index-advisor
--                     story), and is a plausible source of "why is this
--                     database bigger than expected" evidence.
--  * app.event_log -- an ever-growing log table, the kind of thing that
--                     actually eats disk in real deployments. Sized so
--                     pg_database_size / largest-relations queries have
--                     a believable disk-growth story for
--                     tasks/playbooks/playbook-disk-space.md.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS, and the bulk inserts are
-- guarded so `make seed` can re-run this against an already-seeded
-- database without duplicating rows.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app.event_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    level TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app.orders LIMIT 1) THEN
        INSERT INTO app.orders (customer_id, status, created_at, payload)
        SELECT
            (random() * 5000)::int,
            (ARRAY['pending', 'shipped', 'delivered', 'cancelled', 'refunded'])[(random() * 4)::int + 1],
            now() - (random() * interval '365 days'),
            rpad('order-payload-' || md5(random()::text), 400, md5(random()::text))
        FROM generate_series(1, 200000);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM app.event_log LIMIT 1) THEN
        INSERT INTO app.event_log (occurred_at, level, source, message)
        SELECT
            now() - (random() * interval '30 days'),
            (ARRAY['INFO', 'WARN', 'ERROR', 'DEBUG'])[(random() * 3)::int + 1],
            (ARRAY['qa-refresh', 'api', 'batch-loader', 'questdb-sync'])[(random() * 3)::int + 1],
            rpad('synthetic log line for disk-growth seeding ' || md5(random()::text), 300, md5(random()::text))
        FROM generate_series(1, 150000);
    END IF;
END
$$;

ANALYZE app.orders;
ANALYZE app.event_log;

-- Run the slow, missing-index query at least once so pg_stat_statements
-- has a realistic top offender to show for the playbook demo. Safe to
-- run every time (cheap, no side effects beyond the stats entry).
SELECT count(*) FROM app.orders WHERE customer_id = 42 AND status = 'shipped';
