---
depends_on:
  - /tasks/playbooks/playbook-framework.md
  - /tasks/foundation/compose-stack.md
---

# Playbook: filesystem disk space

The flagship (24% of real alert volume; `/quest` and `/local` on the
QuestDB hosts). Given a Check_MK filesystem alert: identify what's
growing, how fast, and time-to-full; hand off to infra with evidence
when the fix is host-level.

Evidence sources — queries and APIs only, no SSH:
QuestDB `table_storage()` / `table_partitions()` for per-table/partition
disk usage; Postgres `pg_database_size`, `pg_tablespace_size`,
`pg_ls_waldir()` summary, largest relations; Check_MK API for the
filesystem series (growth rate → time-to-full). Output includes a
ready-to-paste Jira ticket draft (infra-owned) with the evidence table.

## Deliverables

- [ ] QuestDB storage queries + interpretation notes
- [ ] Postgres size/WAL queries + interpretation notes
- [ ] Check_MK filesystem history pull + linear time-to-full estimate
- [ ] Jira draft template (title, body, evidence, suggested action)
- [ ] Demo scenario in compose stack (seeded growth on the QuestDB volume)
