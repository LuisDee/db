---
depends_on:
  - /tasks/playbooks/playbook-framework.md
  - /tasks/foundation/compose-stack.md
---

# Playbook: tablespace usage

The original motivating case (USER_INDEX_04 near full). Evidence:
`dba_data_files` (incl. autoextend headroom — a "91% full" tablespace
with autoextend room is a different verdict), `dba_free_space`
fragmentation, top segments by growth (`dba_segments` snapshots),
recent extent allocation rate → time-to-full. Output: verdict +
the remediation SQL (`ALTER TABLESPACE ... ADD DATAFILE ...` or
autoextend adjustment) presented as **text in the thread** — the gated
runbook-action path that would execute it is post-POC.

## Deliverables

- [ ] Query set incl. autoextend-aware free-space calculation
- [ ] Growth estimate + time-to-full
- [ ] Remediation SQL drafting rules (sizes/paths proposed from evidence, clearly marked DRAFT — REQUIRES DBA APPROVAL)
- [ ] Demo scenario in compose stack (seeded near-full tablespace in oracle-free)
