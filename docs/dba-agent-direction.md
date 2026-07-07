# DBA agent — direction after alert-inventory review (2026-07-07)

Decisions and reasoning from the discussion following the spec review.
This supersedes the spec's phasing; the spec (v0.1) and review remain
for reference.

## Decisions locked in

1. **No sqitch, at least for now.** The 16-day alert inventory confirms
   the work is almost entirely DBA-operational (disk, replication lag,
   tablespace, health flaps), not schema migrations. Write path, when it
   comes, is runbook-style actions and Jira tickets, not a migration
   plan.
2. **Yes to a Slack listener, consuming the channel directly.** Earlier
   advice ("don't parse Slack, take structured webhooks") assumed a
   single Alertmanager-style source. Reality: heterogeneous providers
   (Check_MK and others) dumped into one channel, ~6 alerts/day. At that
   volume and heterogeneity, the LLM *is* the parser — classification
   and host extraction from message text is exactly what it's good at,
   and brittleness of format-parsing stops being the argument. A direct
   Check_MK webhook (notification plugin) can be added later per-source
   if one ever matters enough; don't block on it.
3. **No SSH in v1.** An LLM-driven bot with shell on prod DB hosts is
   the highest-risk component in the whole design. v1 uses (a) read-only
   DB connections and (b) Check_MK's already-collected host data (it
   knows filesystem usage, processes) via its API. Tightly-scoped SSH
   (dedicated user, forced-command/allowlist, read-only) is a later,
   deliberate addition if a playbook genuinely needs `du`-level detail.
4. **Jira integration is in-plan** (infra-owned problems like Postgres
   host disk need a ticket, not a DB change), but v1 ships a *ticket
   draft in the thread* — title, body, evidence, ready to paste. Live
   Jira API + credentials is the first v1.5 item. (Note: the nock-based
   jira-mock sketch assumes Node; if the agent is Python — likely, given
   existing tooling — the equivalent is `responses`/`respx`. Either way:
   feature first, mock when the feature exists. Building test harnesses
   ahead of features is how the last plan ballooned.)

## What the alert inventory actually says (16 days, ~100 alerts)

| Class | Share | Read |
|---|---|---|
| QuestDB health-check flapping | 34% | Noise with a real cause underneath. Not a per-alert-triage problem — a *fix-it-once* RCA problem (why does QuestDB flap on these hosts?). Also: QuestDB is operationally a concern *today*, despite being "future" in the spec. |
| Nightly QA refresh cycle | 29% | Pure noise + one recurring signal (FK restoration warns most nights). Suppress the Started/Finished spam; RCA the FK warning **once** — plausibly it's our own refresh tooling, and one fix removes 29% of channel volume. |
| Filesystem disk-space | 24% | Real. The flagship playbook: what's growing, time-to-full forecast, evidence, Jira draft to infra. |
| boproddb standby replication lag | 8% | Real. Second playbook: standby gap analysis (archive shipping, gap sequence, transport vs apply lag). |
| Tablespace usage | 2% | Real, rare. Third playbook — and the original motivating case (leads to add-datafile runbook action later). |
| Ad hoc human messages | 3% | One of them literally asks to reduce alert noise. |

Two conclusions the numbers force:

* **~63% of the channel is noise.** The single highest-value action is
  alert hygiene, not alert enrichment. A bot that writes eloquent
  diagnoses under flapping QuestDB checks makes the noise *worse*.
* **~6 alerts/day, and under-alerting is admitted.** Per-alert triage
  saves modest time today. The bigger prize is *coverage*: nothing is
  watching most of what a DBA would want watched (replication beyond one
  DB, backups, Oracle tablespace forecasting, PG autovacuum/WAL,
  connection saturation, long transactions...).

## Where the value actually is (ranked)

1. **Alert hygiene** — suppress the nightly cycle, RCA the QuestDB flap
   and the FK warning once each. Mostly agent-assisted engineering, not
   a system to build.
2. **Alert coverage** — use the agent (interactively at first) to
   inventory each engine and propose an alert catalogue, delivered as
   reviewable monitoring config in git. This directly answers "we
   aren't alerting because we haven't set much up."
3. **Triage bot on the real alerts** — disk, replication lag,
   tablespace: threaded diagnosis + evidence + Jira draft. Small,
   demoable, and the foundation for everything agentic later.
4. **Action routing** — live Jira creation; later, runbook actions
   (add datafile) behind approval.

## POC scope (deliberately small)

Slack listener (Bolt, Socket Mode) on the alerts channel →
LLM classifies message + extracts host/DB → endpoint-registry lookup
(host → engine, DSN, read-only credential ref) → run that alert type's
preset read-only queries → LLM synthesizes → threaded reply:
two-line verdict, evidence, suggested action, Jira-ticket draft when
the fix is infra-owned. 👍/👎 reactions captured.

Three playbooks only: **filesystem disk-space**, **standby replication
lag**, **tablespace usage**. Explicitly out: QuestDB flapping and the
nightly refresh cycle (those get suppressed/fixed, not narrated), SSH,
live Jira, MCP, sqitch, auto-apply anything.

Second deliverable, near-zero cost: **weekly noise digest** — batch job
over the channel's last 7 days: alert counts by class, flap detection,
"suggest we suppress / retune X" list. Given 63% noise, this may earn
more goodwill than the triage bot itself.

## Feature backlog for the agent (post-POC, in rough order)

* Live Jira ticket creation (infra-owned findings).
* @-mention follow-ups in the alert thread, bounded to the read-only
  query catalogue.
* Alert-coverage advisor: per-DB gap analysis → proposed monitoring
  rules as an MR.
* Capacity/growth reports: time-to-full per filesystem and tablespace,
  weekly, with trend charts.
* Scheduled health digests per DB (top SQL, stats freshness, bloat,
  unused/duplicate indexes) — pull-based, low noise.
* Standby/DR posture check (gap, lag trend, FRA usage, backup success).
* Runbook actions behind approval (add datafile, gather stats, simple
  grants) — parameterized templates, MR- or Slack-approval gated.
* Scoped SSH for host-level forensics, if a playbook proves the need.
* Incident-thread summarization (what happened, timeline, follow-ups).

## Decisions — round 2 (2026-07-07, later)

7. **Triage bot confirmed as a must; scheduled DB sweep promoted.** The
   cadence-driven "scan the DBs, find issues, check datafile/tablespace
   headroom, suggest new alerts" agent is committed post-POC scope (it
   reuses the POC's playbook executor — a sweep is playbooks run on a
   timer instead of on an alert).
8. **No SSH, confirmed.** Debugging is queries + Check_MK API. The
   residual host-level gap (e.g. "which non-DB process is eating
   /local") is handled by handing infra a Jira draft with everything we
   *can* see, which is the correct org boundary anyway.
9. **Write gate without sqitch.** The GitLab gate survives; only the
   applier changes. Bot opens MR (runbook-action YAML + rendered SQL) →
   only the DBA group has merge permission on the repo (works on GitLab
   Free; enforced approval rules/CODEOWNERS need Premium) → merge
   triggers a manual "apply" CI job → a tiny applier (psql / sqlplus /
   python-oracledb in the runner image) executes under the
   write-capable identity, records to an audit table, posts the result
   to the originating Slack thread. There is no privileged "write API"
   for PG/Oracle to use instead — writes are SQL over a connection
   either way; the gate is about *who holds the write credentials and
   when they can be used* (never the bot; only the post-approval job).
10. **Oracle is Standard Edition** — constraint recorded: playbooks
   must be license-clean (no AWR/ASH/`dba_hist_*`; Diagnostics Pack is
   EE-only), and Data Guard is EE-only so the boproddb standby is
   presumably scripted/Dbvisit — mechanism to confirm (blocks the
   replication playbook's Oracle query set).
11. **Containers-first proof.** Nothing touches a real host, channel,
   or credential until the full loop passes in the local compose stack
   (postgres:16 + gvenzl/oracle-free + questdb + alert injector). See
   `tasks/poc/e2e-demo.md` for the exit criterion.
12. **Structured Tasks adopted.** Work items and decision history live
   in `tasks/` with the compliance/branch-guard scripts under
   `project-management/scripts/`. Kept deliberately light: the scripts
   and task DAG exist, the mgmt-ui visualizer does not (POC first).

## Open items

* Agent language: Python assumed (matches existing tooling and
  oracledb/psycopg drivers) — confirm.
* Check_MK API access (Livestatus/REST) for host metrics without SSH.
* Jira project + credentials for the infra-ticket path (v1.5).
* Read-only DB identities per engine (from spec §4 — still right).
* Who owns suppressing the nightly refresh spam at the source
  (Check_MK rule vs job config).
