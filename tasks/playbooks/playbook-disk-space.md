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

- [x] QuestDB storage queries + interpretation notes (commit: 92fe6b8 —
      `playbooks/filesystem-disk-space.yaml`'s `table_storage_summary`
      and `metrics_partitions` queries. Column names confirmed against
      QuestDB's own griffin-engine source
      (`TableStorageRecordCursorFactory`,
      `ShowPartitionsRecordCursorFactory` on GitHub) rather than the
      public docs site, which this sandbox's egress policy blocks (same
      restriction noted in `tests/integration/conftest.py` for the
      QuestDB binary download) — **structurally ready, not live-verified**:
      the QuestDB integration test (`test_playbook_disk_space.py`)
      skips cleanly here (no Docker, no reachable QuestDB), the same as
      every other QuestDB-dependent test in this repo)
- [x] Postgres size/WAL queries + interpretation notes (commit: 92fe6b8 —
      `database_size`, `largest_relations`, `wal_summary` in the same
      YAML file — **live-verified** against this sandbox's real local
      Postgres 16 server: `tests/integration/test_playbook_disk_space.py`
      runs all three through the real `load_playbook()` →
      `run_playbook()` → `PostgresRunner` chain and asserts real numbers
      out of the compose seed's `app.event_log`/`app.orders` data)
- [x] Check_MK filesystem history pull + linear time-to-full estimate
      (commit: d768390 for the estimator, a348001 for the Check_MK pull
      — `src/dba_agent/capacity.py`'s `estimate_time_to_full()`/
      `linear_growth_rate()` are pure and fully unit-tested (increasing,
      flat, decreasing, insufficient-data, already-past-capacity cases
      all covered) independent of any live engine.
      `checkmk.filesystem_history()` follows the same
      query-URL/request-body/parse-response pure-function pattern as
      the existing `filesystem_usage()` — **unverified against a live
      Check_MK instance** (spec open question 2: none available), and
      doubly so here since this sandbox's egress policy also blocks
      reaching docs.checkmk.com/the Checkmk forum to confirm the REST
      API 1.0 "get a single metric" schema directly; the shape is a
      best-effort reconstruction from search-engine summaries plus the
      older Web API's `start_time`/`step`/`rrddata` encoding — flagged
      prominently in the module docstring as the least trustworthy
      piece of this task until proven against a real site)
- [x] Jira draft template (title, body, evidence, suggested action)
      (commit: ec5a8a5 — `src/dba_agent/jira_draft.py`'s
      `build_jira_draft()`; pure string-building from an evidence
      bundle + optional `CapacityEstimate` + infra-vs-DB owner tag, no
      I/O, no Jira SDK — fully unit-tested, matches
      `docs/dba-agent-direction.md` decision 4 (draft in-thread in v1,
      live Jira API is v1.5))
- [x] Demo scenario in compose stack (seeded growth on the QuestDB
      volume) (already shipped by `tasks/foundation/compose-stack.md` —
      `compose/questdb/seed.py`'s ~200k-row/30-day baseline plus a
      ~100k-row/3-day recent burst on the `metrics` table, and
      `compose/postgres/init/03_schema_seed.sql`'s `app.event_log`
      table, both built specifically for this playbook's disk-growth
      story; commit: 92fe6b8 is this playbook's queries actually
      reading that seeded growth and, for Postgres, proving it live)
