---
depends_on:
  - /tasks/playbooks/playbook-framework.md
  - /tasks/foundation/compose-stack.md
---

# Playbook: standby replication lag

boproddb-style alert: standby falling behind primary by N logs. Oracle
Standard Edition caveat — Data Guard is Enterprise-only, so the standby
mechanism is presumably scripted log shipping or a Dbvisit-style tool:
**confirm the actual mechanism before finalising queries** (open item).
SE-safe evidence: `v$archived_log` applied vs shipped sequence,
`v$log_history` rates, archive destination errors (`v$archive_dest`),
redo generation rate (to distinguish "standby slow" from "primary
bursty"). Postgres side (for the same playbook class):
`pg_stat_replication`, `pg_stat_wal_receiver`, replay lag bytes.

Compose-stack note: a live Oracle standby is out of POC scope — this
playbook is developed against recorded fixture result-sets, plus live
Postgres streaming replication (cheap to stand up in compose) for the
PG variant.

## Deliverables

- [ ] Confirm boproddb standby mechanism (blocks Oracle query set)
- [ ] Oracle SE-safe query set + interpretation notes (fixture-tested)
- [ ] Postgres replication query set, live-tested in compose
- [ ] Verdict logic: shipping problem vs apply problem vs primary burst
