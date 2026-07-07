# Integration tests

Unlike everything under `tests/*.py` (unit tests, fakes injected at
every boundary), these tests run against a **real** database engine.
They exist because unit tests alone let every task pass its own tests
while the seams between tasks — and every line of SQL shipped in
`compose/` — go completely unproven. See
`tasks/foundation/integration-test-infra.md`.

## Running

```
pytest -m integration            # runs only these
pytest                            # runs everything EXCEPT these (default;
                                   # see addopts in pyproject.toml)
```

## How a fixture gets its engine

Each fixture (`postgres_dsn`, `oracle_dsn`, `questdb_host_port` in
`conftest.py`) tries, in order:

1. **A `*_TEST_DSN` env var override** — point it at any already-running
   instance (a local install, a shared dev DB, whatever). The fixture
   never touches that instance's configuration (e.g. it won't try to
   set `shared_preload_libraries` for you) — if a check needs something
   the override instance doesn't have configured, that specific test
   skips with a message telling you what to set up, rather than
   silently mutating someone else's database.
2. **A `testcontainers` container**, mirroring the exact image/config
   `compose/compose.yaml` uses. This is what runs on a real Docker host
   with no env vars set.
3. **A clean `pytest.skip`**, with the actual underlying error in the
   reason, if neither is available. Never an error — an environment
   without Docker (like the one this was built in) should show `SKIPPED`
   with a reason, not a failure.

## What's actually been proven, and how

| Engine | In this sandbox (no Docker) | On a machine with Docker |
|---|---|---|
| **Postgres** | **Live-verified for real.** No Docker needed for this one — a local `apt`-installed Postgres 16 server was started, configured with `shared_preload_libraries=pg_stat_statements` (mirroring `compose.yaml`'s `command:` flag), and `POSTGRES_TEST_DSN` pointed at it. All 5 tests passed against the real engine: every `.sql` file in `compose/postgres/init/` applies cleanly (twice, proving the idempotency `make seed` relies on), the replication role exists, the seeded schema has the expected shape (including the *absence* of an index — that's deliberate), and `pg_stat_statements` genuinely captures a real query end-to-end. | Same tests, via the `testcontainers` path instead — should behave identically. |
| **Oracle** | Skips cleanly (no Docker, `ORACLE_TEST_DSN` unset). No realistic non-container way to run a real Oracle instance in this sandbox. | **Not yet proven anywhere** — first real run of `test_near_full_tablespace_seeded` happens here. This is `compose/README.md`'s #1 "check this first" item: does the fill loop actually land in a believable 80–99% range? |
| **QuestDB** | Skips cleanly (no Docker; downloading QuestDB's standalone binary is also blocked — `download.questdb.io` returned 403, not on this sandbox's egress allowlist). | **Not yet proven anywhere** — first real run happens here. |

**Bottom line for whoever runs this next on real Docker:** Postgres
should just work (it already has, against an equivalent real engine).
Oracle and QuestDB are where the actual remaining risk lives — run
`pytest -m integration` there first and expect those two to be the ones
that might need adjustment.
