---
depends_on:
  - /tasks/foundation/endpoint-registry.md
  - /tasks/foundation/integration-test-infra.md
---

# Playbook framework

A playbook = YAML metadata + a set of **preset, read-only** SQL/API
queries per engine + interpretation notes. The executor resolves the
endpoint, runs the playbook's queries under the read-only identity, and
produces an evidence bundle (query, result, timing) for synthesis. The
LLM selects and interprets playbooks; it never authors SQL (the
Xata/HolmesGPT/pganalyze convergence).

Constraints: Oracle queries must be Standard-Edition-safe and
license-clean — no AWR/ASH/Diagnostics-Pack views (`v$active_session_
history`, `dba_hist_*` are off-limits); use `v$`/`dba_` base views and
Statspack if installed. Literal values in any captured SQL text get
redacted before leaving the agent.

## Deliverables

- [x] Playbook file format + loader/validator (commit: 36870cb)
- [x] Executor: per-query timeouts, partial-failure tolerated, evidence bundle (commit: c60cdc5 — see below)
- [x] Read-only enforcement: connections opened read-only where the driver supports it; identity has no write grants (defence in depth) (commit: c60cdc5 — **live-verified**: `conn.read_only=True` actually rejects a write with `psycopg.errors.ReadOnlySqlTransaction` against a real Postgres server, and a real `dba_agent_ro` role with only SELECT/pg_monitor grants was created locally to run the executor's fixed-username path for real)
- [x] Literal-redaction pass on captured query text (commit: 36870cb; **live-verified** against real captured query text — see integration note below)
- [x] Check_MK API client for host-level facts (filesystem usage) — no SSH (commit: c60cdc5 — unit-tested only; no live Check_MK instance available, matches spec open question 2; request/response shape follows Check_MK's public REST API 1.0 docs, unverified against a real site)
- [x] Unit tests assert on SQL strings constructed, not DB side effects (commit: c60cdc5 — `_build_postgres_dsn`/`_statement_timeout_sql`/`_filesystem_query_url`/`_parse_filesystem_response` are all pure functions, unit-tested directly)

Integration note: `tests/integration/test_playbook_executor.py` proves
read-only enforcement and redaction against a real engine, not fakes.
The redaction test deliberately does **not** use `pg_stat_statements`
for the "needs redaction" proof — verified empirically that Postgres
normalizes literal constants into `$1` placeholders in that view
itself, so a test against it would pass whether or not
`redact_literals()` ever ran. `pg_stat_activity.query` is genuinely
unnormalized and is what the test actually exercises.
