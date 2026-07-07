---
depends_on:
  - /tasks/foundation/endpoint-registry.md
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

- [ ] Playbook file format + loader/validator
- [ ] Executor: per-query timeouts, partial-failure tolerated, evidence bundle
- [ ] Read-only enforcement: connections opened read-only where the driver supports it; identity has no write grants (defence in depth)
- [ ] Literal-redaction pass on captured query text
- [ ] Check_MK API client for host-level facts (filesystem usage) — no SSH
- [ ] Unit tests assert on SQL strings constructed, not DB side effects
