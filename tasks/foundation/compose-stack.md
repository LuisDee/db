---
depends_on:
  - /tasks/foundation/agent-skeleton.md
---

# Local compose stack

Prove-it-locally environment: docker-compose with all three engines and
a synthetic alert injector, so the full loop runs on a laptop with zero
access to real infrastructure. This is the contract from the direction
doc: nothing gets plugged into a real host until the loop is proven
here.

Services: `agent`; `postgres:16` (pg_stat_statements preloaded, seeded);
`gvenzl/oracle-free:23-slim` (seeded schema + a tablespace pushed near
full); `questdb/questdb` (seeded tables); `alert-injector` (script that
posts recorded real alert texts — Check_MK format from the 16-day
sample — into the fake/real Slack channel).

## Deliverables

- [x] compose file; all services healthy from cold start, documented RAM budget (commit: d07daa3, d91f1db — `docker compose config` validated clean (no reachable Docker daemon in this environment: client present, daemon socket absent — confirmed via `docker version`); cold-start healthiness itself is **not** live-verified, see compose/README.md's "what to check first" list)
- [x] Seed scripts per engine (incl. near-full Oracle tablespace scenario) (commit: d07daa3 postgres, d789855 oracle, e63a0bb questdb — all idempotent, `bash -n`/`py_compile` clean; actual execution against live engines is parse-only/not verified here, see compose/README.md)
- [x] Alert injector with a corpus of ~10 real (anonymised) alert messages (commit: 2792401 — live-verified: `PYTHONPATH=src python3 compose/injector/inject.py --type <slug>` run for every fixture type and `--type all` against the real `dba_agent.slack` module, output log round-tripped)
- [x] Makefile targets: `make up`, `make seed`, `make inject-alert TYPE=...` (commit: d91f1db — targets present and `make -n`/`make help` dry-run clean; the docker-compose-backed targets (`up`, `seed`) are parse-only-verified, not run end-to-end, see compose/README.md)
- [x] Works with in-memory Slack fake; optional real test-workspace mode (commit: 2792401 — `FakeSlackClient` path live-verified as above; `RealSlackClient`/`SLACK_MODE=real` path is code-reviewed only, no real Slack workspace exercised)
