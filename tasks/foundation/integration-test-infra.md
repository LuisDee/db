---
depends_on:
  - /tasks/foundation/agent-skeleton.md
  - /tasks/foundation/compose-stack.md
  - /tasks/foundation/endpoint-registry.md
---

# Integration test infrastructure

Every task so far has been tested in isolation with fakes — real
`AnthropicLLMClient`/`RealSlackClient` have never been exercised, no
SQL in `compose/` has ever touched a real engine, and nothing has
proven the seams between tasks (an `Endpoint`'s DSN is actually
connectable; a playbook's SQL actually runs). This task closes that gap
going forward, mirroring the convention already established in the
sibling `oracle-schema-refresh` repo: `tests/integration/`, gated by
`@pytest.mark.integration`, deselected by default via `addopts`,
backed by testcontainers with a `*_TEST_DSN` env-var override for
pointing at an already-running instance. Every task from here on that
touches a real engine should add an integration test here, not defer
proof to `poc/e2e-demo`.

Docker is unavailable in this build environment (confirmed: daemon
won't start). Where that's true, the Postgres path is verified for
real anyway using a locally-installed Postgres server (no Docker
required for that engine) via the DSN-override path; Oracle and
QuestDB fixtures are testcontainers-only and skip cleanly with a clear
reason here — they get real coverage the moment this runs on a Docker
host. State plainly in the task file which is which; don't claim
verified what wasn't.

## Deliverables

- [x] `pytest` `integration` marker registered; deselected by default (`addopts = "-m 'not integration'"` or equivalent), `pytest -m integration` runs them explicitly (commit: 75d80a7)
- [x] `tests/integration/conftest.py`: per-engine fixtures (postgres, oracle, questdb) — testcontainers-based by default, honouring `POSTGRES_TEST_DSN`/`ORACLE_TEST_DSN`/`QUESTDB_TEST_DSN` env vars to point at an existing instance instead; skip cleanly with a clear reason (not an error) when neither Docker nor a DSN override is available (commit: b561cd0 — includes a fix mid-build: `DockerContainer(...)` construction itself, not just `.start()`, talks to the Docker client, so both must share one try/except or a missing daemon errors instead of skipping)
- [x] Real Postgres integration test: `compose/postgres/init/*.sql` actually executes against a real engine end-to-end; `pg_stat_statements` extension loads and is queryable; seeded schema (`app.orders`/`app.event_log`) present with expected shape afterward (commit: b561cd0 — **live-verified**: ran for real against a locally-installed Postgres 16 server, `POSTGRES_TEST_DSN` override path, all 5 tests passed twice over including idempotency)
- [x] Oracle and QuestDB fixtures scaffolded to the same contract (testcontainers + DSN override + clean skip) even though they can't be proven live in this environment — structurally ready to run for real on the first Docker-capable machine (commit: b561cd0 — confirmed clean `SKIPPED` with a clear reason, not an error, when neither Docker nor a DSN override is present)
- [x] `tests/integration/README.md` (or a section in the root `README.md`) documenting how to run (`pytest -m integration`), what each fixture proves, and — honestly — what has and hasn't been run live in this environment (commit: b561cd0)
