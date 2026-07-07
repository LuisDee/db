# compose/ -- local proof environment

Docker Compose stack for `tasks/foundation/compose-stack.md`: the
containers-first proof environment the whole project's safety model
depends on ("nothing gets plugged into a real host until the loop is
proven here" -- `docs/dba-agent-direction.md`).

Run everything from the repo root via the `Makefile`; see `make help`.

```
make up                             # build + start, wait for all healthy
make seed                           # idempotent re-seed of all three engines
make inject-alert TYPE=disk-space   # post one alert-fixture class (fake Slack by default)
make down                           # stop (keeps data)
make clean                          # stop and wipe volumes
```

First time: `cp compose/.env.example compose/.env` (dev-only placeholder
values -- see that file's comments; nothing in it is a real secret and
nothing real should ever go in it).

## Layout

```
compose/
  compose.yaml            # the stack: agent, postgres, postgres-replica, oracle, questdb
  .env.example             # dev-only placeholders; copy to .env (gitignored)
  registry.yaml             # self-contained endpoint notes (NOT wired to any registry loader code)
  postgres/init/            # docker-entrypoint-initdb.d scripts (run once, first boot)
  postgres-replica/         # Dockerfile + entrypoint for the streaming standby
  oracle/init/               # container-entrypoint-initdb.d scripts (run once, first boot)
  questdb/seed.py            # post-boot seed via QuestDB's REST /exec (no init-on-boot mechanism exists)
  injector/                  # alert-fixture corpus + injector script
```

## Services

- **agent** -- builds from the repo-root `Dockerfile` (the agent
  skeleton from `tasks/foundation/agent-skeleton.md`). Needs
  `ANTHROPIC_API_KEY` / `SLACK_BOT_TOKEN` to start (dev placeholders from
  `.env`); today it only runs the `/healthz` server, no DB or Slack
  wiring yet -- that lands with `listener/slack-listener` and
  `playbooks/playbook-framework`.
- **postgres** -- `postgres:16`, `pg_stat_statements` preloaded
  (`shared_preload_libraries` set via `command:`, since that setting
  needs a server restart and can't be applied by `CREATE EXTENSION`
  alone) and enabled (`CREATE EXTENSION` in
  `postgres/init/02_extensions.sql`). Seeded
  (`postgres/init/03_schema_seed.sql`) with `app.orders` (no index on
  the columns a lookup query filters on -- a real slow-query /
  missing-index story for `pg_stat_statements` to surface) and
  `app.event_log` (an ever-growing log table, sized to give
  `pg_database_size` / largest-relations queries a believable
  disk-growth story for `tasks/playbooks/playbook-disk-space.md`).
- **postgres-replica** -- streaming standby of `postgres`, built from
  `postgres-replica/Dockerfile` (a thin wrapper around `postgres:16`
  that takes a `pg_basebackup -R` from the primary on first start, then
  hands off to the normal entrypoint). Exists to develop
  `tasks/playbooks/playbook-replication-lag.md`'s Postgres query set
  (`pg_stat_replication` on the primary, `pg_stat_wal_receiver` here)
  against something real, per that playbook's own compose-stack note.
- **oracle** -- `gvenzl/oracle-free:23-slim`. Seeded
  (`oracle/init/*.sql`) with a `USER_INDEX_04` tablespace on a 20M,
  non-autoextend datafile filled to ~90% used -- the near-full
  tablespace scenario for `tasks/playbooks/playbook-tablespace-usage.md`
  (named to match that playbook's own motivating example). All seed SQL
  is plain DDL/DML against `dba_data_files`/`dba_free_space` -- no
  AWR/ASH/`dba_hist_*`, consistent with the Standard Edition,
  license-clean constraint (`README.md`, `docs/dba-agent-spec.md` §6).
  Oracle Free's first-boot database creation is slow (documented as up
  to 1-2 minutes); the healthcheck's `start_period`/`retries` are
  generous on purpose.
- **questdb** -- `questdb/questdb`. Unlike Postgres/Oracle there is no
  init-on-first-boot mechanism, so seeding happens post-boot via
  `questdb/seed.py`, which polls the REST `/exec` endpoint itself before
  seeding (independent of Docker's own healthcheck -- see the note
  below) and creates a `metrics` WAL table partitioned by day, with
  ~300k synthetic rows spread over the last ~30 days (denser in the
  last 3 days, for a plausible accelerating-growth story) --
  `table_storage()`/`table_partitions()` evidence for
  `tasks/playbooks/playbook-disk-space.md`.

## RAM budget

| Service | `mem_limit` | Why |
|---|---|---|
| oracle | 3g (2g reservation) | Oracle Database Free's own licensing caps DB memory (SGA+PGA) at 2GB; real container overhead (background processes, listener) typically lands the whole container around 2-3GB. |
| postgres | 512m | Small seed data (~350k rows total across two tables); plenty of headroom. |
| postgres-replica | 512m | Same order as the primary. |
| questdb | 1g | Time-series engine, but ~300k rows at this scale is light. |
| agent | 256m | Skeleton app, no DB connections yet. |

**Total: ~5.3GB.** Give Docker at least 6GB of memory, 8GB more
comfortably, especially if running all five services plus your own
tooling on the same laptop.

## What's live-verified vs. parse-only in this environment

This stack was built in an environment with the Docker Engine **client**
but no reachable daemon (`docker version` succeeds, `docker compose
up`/`build` fail with "cannot connect to the Docker daemon" --
confirmed to be an environment limitation, not a project decision; see
`tasks/foundation/compose-stack.md` for the exact commit-by-commit
evidence). Concretely, what was and wasn't run:

- **Live-verified**: `docker compose config` against `compose/compose.yaml`
  with `compose/.env` populated -- validates successfully, no warnings,
  confirms all `build.context` paths, volume mounts, env-var
  interpolation (including the `${VAR:?...}` required-var guards),
  and the missing-`.env` failure mode (`docker compose config` fails
  with a clear error naming the missing variable when `compose/.env` is
  absent -- proves `make up`'s dependency on that file actually gates
  correctly). Shell scripts checked with `bash -n`. Python scripts
  checked with `py_compile`.
- **Live-verified**: the alert injector's actual logic --
  `PYTHONPATH=src python3 compose/injector/inject.py --type <slug>` (and
  `--type all`) run end-to-end against the real `dba_agent.slack`
  module from this repo, for every fixture in the corpus, writing and
  reading back `compose/injector/out/injected-alerts.json`. This is the
  one piece of application logic in this deliverable that doesn't need
  Docker at all to prove, so it was actually run, not just read.
- **Parse-only (not live)**: everything that needs a real daemon --
  container builds (`agent`, `postgres-replica`), all three engines'
  actual startup/healthcheck behavior, the SQL seed scripts executing
  against a real Postgres/Oracle instance, `questdb/seed.py`'s HTTP
  calls against a real QuestDB, and end-to-end `make up` / `make seed`
  / `make inject-alert` runs.

**What to check first on a real Docker host, in priority order:**

1. **The `questdb` healthcheck.** `questdb/questdb`'s runtime image is
   `fedora-minimal`/`ubi-minimal`-based and does not ship `curl` or
   `wget` (checked against the upstream Dockerfile) -- the healthcheck
   here uses bash's `/dev/tcp/127.0.0.1/9003` to test the min health
   server's port is open, on the assumption the base image has `bash`.
   If it doesn't, `docker compose up --wait` will report `questdb`
   unhealthy indefinitely even though the DB is fine. Fix if that
   happens: relax/replace the healthcheck block (or set `disable: true`
   on it) -- `make seed` does its own independent host-side HTTP
   readiness poll in `questdb/seed.py` and does not depend on this
   Docker-level check being correct.
2. **The Oracle tablespace fill loop's actual fill percentage.** The
   PL/SQL in `oracle/init/02_fill_tablespace.sql` targets ~90% used
   computed from `dba_data_files`/`dba_free_space`, but block-size and
   segment-header overhead weren't measured against a real instance --
   confirm it lands in a believable "near full" range (not 100%/failed,
   not 50%/not-near-full) and adjust `v_batch`/the 0.90 target if not.
3. **Streaming replication actually catching up.** `postgres-replica`'s
   `pg_basebackup -R` approach is the standard pattern for this, but
   wasn't run against a live primary -- confirm `pg_stat_wal_receiver`
   on the replica shows `streaming` and `pg_stat_replication` on the
   primary shows the replica, once both containers are healthy.
4. Everything else (Postgres/Oracle seed SQL, the agent Dockerfile
   build) already had a lower-risk dry run in
   `tasks/foundation/agent-skeleton.md`'s own verification (isolated
   venv + subprocess, not the container) or is plain, unremarkable
   DDL/DML -- lower priority to double-check first, but still not
   *proven* against a real engine by this deliverable.

## Alert injector

`make inject-alert TYPE=<slug>` posts one class of alert from
`injector/fixtures/alerts.json` (~10 real-shaped, anonymised messages
spanning the 16-day alert inventory's classes -- see
`docs/dba-agent-direction.md`) through `dba_agent.slack`'s
`FakeSlackClient` (default) or `RealSlackClient` (`SLACK_MODE=real`,
needs `SLACK_BOT_TOKEN` + `SLACK_TEST_CHANNEL` in `compose/.env`). Fake
mode's posts are logged to `compose/injector/out/injected-alerts.json`
(gitignored) so the target has an observable result without any real
Slack workspace. Known `TYPE` values: `questdb-health-flap`,
`qa-refresh`, `disk-space`, `replication-lag`, `tablespace-usage`,
`human`, or `all`.

**Scope boundary** -- this proves alert delivery works and that the
three databases are seeded and queryable. It does not wire an injected
alert through an actual listener or classifier (those don't exist yet:
`listener/slack-listener`, `listener/alert-classifier` are separate,
not-yet-started tasks). The real end-to-end wiring is
`tasks/poc/e2e-demo.md`'s job, not this one's.
