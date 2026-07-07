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

- [ ] compose file; all services healthy from cold start, documented RAM budget
- [ ] Seed scripts per engine (incl. near-full Oracle tablespace scenario)
- [ ] Alert injector with a corpus of ~10 real (anonymised) alert messages
- [ ] Makefile targets: `make up`, `make seed`, `make inject-alert TYPE=...`
- [ ] Works with in-memory Slack fake; optional real test-workspace mode
