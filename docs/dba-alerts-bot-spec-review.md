# Adversarial review of `dba-alerts-bot-spec.md` (draft v0.1)

> Written 2026-07-07. Straw-mans the spec against the stated motivation:
> *"the main motivation is to build the foundation [for agentic stuff].
> Easy wins out of the gate: slack bot integration to respond to alerts,
> do some debugging and post a comment stating what the alert was, to give
> the DBA some insight; create suggested changes (DDL/DCL) as a merge
> request gated by DBA review — e.g. Oracle needs a new datafile, it
> raises the SQL and we approve."*

## Verdict

The spec is technically literate and most of its individual claims check
out. But it is the wrong spec for the stated goal: it describes a
**database change-management platform** with an AI author bolted on, while
the thing you called the easy win — respond to an alert, debug it, post
insight — is deferred to **Phase 3**. Worse, the spec's own proposal
whitelist (§9) *explicitly excludes* your motivating example (datafile
operations). Roughly 60% of the document (sqitch, CI topology, ports &
adapters, mock matrix, compose topology) is scaffolding for the part of
the system that should come second.

Keep the security model and the governance direction. Invert the phases.
Cut the architecture ceremony. Add the two things the spec is missing
entirely: an **alert inventory** and the **playbooks themselves**.

## What the spec gets right — keep these

* **Two-identity separation** (read-only agent vs. migration identity used
  only by CI), enforced at the grant level. Non-negotiable; keep verbatim.
* **AI never writes to prod; human MR review is the gate; a second manual
  gate before prod deploy.** Correct and correctly layered.
* **Revert scripts for irreversible operations must fail loudly, not
  no-op.** Genuinely good rule; most teams get this wrong.
* **Idempotency/dedup thinking** in §13 (Slack redelivery, MR spam from
  flapping alerts, crash-and-restart double-open). All real; all needed.
* **Egress check for `api.anthropic.com` from Foundry** — validate in week
  one, it is the classic silent killer.
* **Rejecting Alembic/ORM diffing for DCL/operational SQL.** Correct.
* **Non-goals list** (§3). Sensible scope fencing.

## Major objections

### 1. The phase order is inverted relative to your motivation

Spec order: telemetry → scheduled advisory → **write path (sqitch + CI +
MR)** → alert-driven RCA. Your stated easy win is alert-driven RCA. It is
scheduled *after* the entire GitLab/sqitch/CI apparatus. That ordering
maximises time-to-first-value and means the first thing DBAs see from
this project is process change (a migration tool and a pipeline), not
help. Alert-triggered diagnosis needs none of the write path: it needs a
Slack bot, a read-only DB role, curated diagnostic queries, and a Claude
call. Build that first; it is also the foundation the agentic future
actually rests on (the context-gathering and reasoning loop).

### 2. The spec excludes your own motivating use case

§9 recommends the Phase 2 whitelist "explicitly excluding
tablespace/datafile … operations until trust is established". Your worked
example — tablespace-full alert → bot proposes `ALTER TABLESPACE ... ADD
DATAFILE` → DBA approves — is therefore out of scope of the spec as
written. Either the whitelist is wrong or the example is. (The resolution
is objection 3: datafile addition doesn't belong in the *migration* path
at all, so the whitelist-vs-example tension is a symptom of a modelling
error, not a trust question.)

### 3. Category error: operational actions are not schema migrations

sqitch's model is a **linear plan of changes applied identically to every
environment**, with deploy/revert/verify semantics. That fits schema DDL
(create index, add column, create role). It does not fit operational
actions:

* `ALTER TABLESPACE ADD DATAFILE '/u02/oradata/PROD/users03.dbf' SIZE 32G`
  is environment-specific (paths, sizes, ASM vs filesystem differ between
  staging and prod), has no meaningful revert (you cannot just drop a
  datafile with data in it), and "deploy to staging first" is close to
  meaningless — staging doesn't have prod's space pressure.
* The same applies to `DBMS_STATS` runs, session kills, vacuum/analyze,
  resizing, and most of what an alert-response bot would actually propose.

Forcing these through a migration plan pollutes the migration history
with one-off operational events and forces fake revert/verify scripts.
You need **two write paths**, not one:

1. **Schema changes** → migration tool (sqitch or otherwise), linear
   plan, staging-first. Rare for this bot.
2. **Operational runbook actions** → parameterized, pre-approved action
   templates (`add_datafile(tablespace, size)`, `gather_stats(schema,
   table)`), stored in git, instantiated by the bot with filled-in
   parameters, approved via MR or even a Slack approval step, executed by
   a CI job with the migration identity, logged to an audit table. The
   template is reviewed once by a DBA; each *invocation* is approved
   individually. This is the path your datafile example lives on, and it
   is much easier to trust than free-form LLM SQL because the DBA reviews
   parameters, not statements.

### 4. sqitch adoption is an organisational change project hiding inside a bot spec

"Make every DB change — human or AI — go through sqitch" means: registry
tables installed in every prod database, all human DBA changes moving to
deploy/revert/verify triplets, a repo-per-target, and a runner image
carrying Perl + `DBD::Oracle` + Instant Client. That is a change to how
the whole team works, requiring buy-in the spec never mentions, and its
Oracle engine is the least-travelled path in sqitch. It may well be the
right end state — but couple the bot's v1 to it and both projects can
sink together. Decouple: the bot's first proposals can be **plain `.sql`
files in an MR** (or runbook-template invocations per objection 3),
applied by a simple CI job. Adopt sqitch (or another migration tool) as a
separate, team-level decision.

### 5. The playbooks are the product, and the spec doesn't contain any

The quality of this system is almost entirely determined by the content
of the per-alert-type playbooks: which `v$` / `pg_stat_*` queries to run
for which alert, what "normal" looks like, what evidence to include. The
spec spends ~2,000 words on ports, mocks, and compose topology and one
parenthetical on playbooks. There is also **no inventory of the alerts
you actually receive today** — the single most important input. First
deliverable of the project should be: pull 60–90 days of alerts from the
channel, rank by frequency and by time-burned, pick the top 3–5, and
write those playbooks (initially just as SQL + interpretation notes a
DBA agrees with). If a playbook's diagnosis is useful *when run by hand*,
the bot will be useful; if not, no architecture will save it.

### 6. Ingesting alerts by parsing Slack messages is brittle

§6.1 subscribes to the existing Slack alert channel, i.e. parsing the
text some other bot posted. Alert text formats drift; parsing them is the
flakiest possible ingestion. If alerts originate from Prometheus
Alertmanager (or Grafana Alerting), add the agent as an **additional
webhook receiver** and get structured JSON (labels: instance, db,
severity, alertname) instead of prose. Then the only Slack-side work is
posting the diagnosis — ideally as a **thread reply** on the alert
message (correlate via alert fingerprint in the message, or have the
agent post the alert itself and own the thread). Related gap: the spec
never says how an alert maps to a connectable endpoint. You need an
**endpoint registry** (alert labels → DSN + engine + credentials ref) —
you already have exactly this pattern in `oracdb`'s endpoints registry;
reuse the idea.

### 7. MCP is probably the wrong tool layer for v1

For a purpose-built headless agent running fixed playbooks, a **curated
catalogue of diagnostic queries executed directly** (psycopg /
python-oracledb under the read-only role) is simpler, deterministic,
testable, and auditable. The spec's MCP choices add real weight:

* SQLcl MCP server drags a JVM + SQLcl subprocess into the agent
  container and is designed around interactive developer use;
* `postgres-mcp` is a young project to take a hard runtime dependency on;
* stdio-subprocess supervision (§13) is a failure class you simply don't
  have if the agent queries the DB itself.

MCP earns its place later, when you want open-ended agentic exploration
("Claude, poke around and figure it out") rather than playbook execution
— and at that point the Claude Agent SDK with custom tools (your curated
queries exposed as tools) gets you the same flexibility with less
machinery. Keep MCP as a Phase-later option, not the v1 foundation.

### 8. Ports-and-adapters ceremony is oversized for v0

Four formal ports, mock + live adapter per port, a MOCK/LIVE env matrix,
`slack-mock` as an optional HTTP harness, a six-step adapter-flip
sequence, and a compose topology — before a single playbook exists. The
underlying instinct (inject dependencies, fake them in tests) is right
and needs about one paragraph: *constructor-inject the DB client, LLM
client, Slack client, and proposal writer; use fakes in unit tests;
integration-test against real containers.* You already run
testcontainers + `gvenzl/oracle-free` in `oracle-schema-refresh` — reuse
that pattern. Delete §10–§12's ceremony from the spec and let the code
have ordinary seams. (Keeping QuestDB in the doc also contradicts your
own "not a concern now" — the DI seam covers future engines by
construction; cut §10's QuestDB adapter discussion.)

### 9. Oracle is excluded from the POC on a false premise

§11.2: "A local Oracle container is heavyweight and licensing-encumbered."
Wrong on both counts for this purpose: `gvenzl/oracle-free:23-slim` is
freely usable, starts in tens of seconds, and **your own
`oracle-schema-refresh` integration suite already uses it via
testcontainers**. Meanwhile Oracle is where your motivating pain
(datafile/tablespace alerts) lives. A Postgres-only POC proves the loop
on the easy engine and defers the one you asked for. Run both engines in
the POC.

### 10. Missing from the spec entirely

* **Success metrics / feedback loop.** Nothing measures whether diagnoses
  are useful. Track: diagnoses posted, 👍/👎 reactions from DBAs,
  proposals opened vs merged vs closed-unmerged, time-to-diagnosis vs
  baseline. A bot that gets ignored fails silently without this.
* **Noise budget.** A bot that posts an essay on every alert gets muted
  within a month. Respond only to playbooked alert types; lead with a
  2-line verdict, details collapsed/threaded; stay silent when the
  playbook finds nothing beyond the alert itself.
* **PII/data leakage via query text.** `pg_stat_statements` and `v$sql`
  contain SQL with literals. Posting raw query text into Slack can leak
  customer data into a new system of record. Normalize/redact literals
  before anything leaves the agent.
* **Interactivity.** "Respond to alerts" plausibly includes a DBA asking
  the bot follow-ups in the thread ("@bot show the execution plan").
  Fire-and-forget reports are specced; conversation isn't. It's cheap
  with Socket Mode and it's where the agentic foundation shows value.
* **Socket Mode vs Events API.** For an internal bot on Foundry, Slack
  Socket Mode needs no public ingress and removes the 3-second-ack
  public-endpoint dance §13 worries about (dedup still needed). The spec
  picked the harder transport without discussing it.
* **LLM spend control on the advisory path.** §13 rate-limits MRs but not
  Claude calls; an alert storm (one flapping host, 200 alerts) is also a
  token storm. Debounce per alert-fingerprint with a cooldown window.
* **`pg_stat_statements` needs `shared_preload_libraries`,** i.e. a
  Postgres restart — a maintenance-window item, not a checkbox. Worth
  saying out loud in Phase 0.
* **Baseline capture.** Several playbooks need "what does normal look
  like" (stat snapshots over time). Prometheus partially covers this; the
  spec should say which diagnoses depend on history existing (i.e. why
  Phase 0 telemetry genuinely is a dependency for *some* playbooks, not
  all).

## What you actually need to build (revised shape)

**Step 0 — one-week infrastructure spike (kills the three real risks):**
a hello-world container on Foundry that (a) connects read-only to one
prod/staging Postgres *and* one Oracle, (b) calls the Anthropic API,
(c) posts to Slack. If any leg fails (egress, network path, credentials),
you've learned it in week one instead of month three. In parallel:
alert inventory (top 3–5 alert types by frequency over 90 days) and
confirm the alert source (Alertmanager? Grafana? scripts?).

**v1 — the easy win (this is the whole first release):**
alert (structured webhook preferred, Slack channel fallback) → look up
endpoint in registry → run that alert type's playbook queries via
psycopg/python-oracledb under the read-only identity → Claude synthesizes
a diagnosis from the evidence → threaded Slack reply: 2-line verdict +
evidence + suggested fix *in words, with the SQL included as text*.
No write path, no sqitch, no MCP, no MR. Python; Slack Bolt (Socket
Mode); playbooks as data (YAML/SQL files in git, DBA-reviewed).
Enable `pg_stat_statements` as part of this.

**v1.5 — trust builders:** 👍/👎 feedback capture; @-mention follow-up
questions in the thread (bounded to the same read-only query catalogue);
dedup/cooldown per alert fingerprint.

**v2 — the write path, split in two:**
(a) *runbook actions*: parameterized templates (add datafile, gather
stats, simple grant) instantiated by the bot, approved via MR or Slack
approval, executed by a CI job under the migration identity, audited.
This covers the datafile example. (b) *schema changes* (indexes etc.):
MR with plain SQL first; adopt sqitch/a migration tool as a separate
team decision if and when human changes move to it too. Two identities,
denylist, loud-fail reverts, staging-first for schema changes — all
retained from the spec.

**Later — agentic expansion:** open-ended investigation beyond playbooks
(Claude Agent SDK or MCP toolset), scheduled health sweeps, Phase-4-style
narrow auto-apply. QuestDB when it exists as a concern.

## Questions to answer before rewriting the spec

1. What are the top 5 alert types by volume, and what does the DBA do
   today for each? (This *is* the playbook spec.)
2. What emits the alerts — Alertmanager, Grafana, OEM, cron scripts —
   and can the agent be added as a webhook receiver?
3. Does Foundry have egress to `api.anthropic.com` and a network path to
   the DBs? (Step 0 spike answers this empirically.)
4. Do human DBA changes go through any tooling today? (Determines whether
   sqitch adoption is an upgrade or an imposition.)
5. Oracle: self-managed vs Autonomous, and Diagnostics Pack licensing
   (AWR/ASH vs Statspack/`v$`) — kept from spec §4/§9, still the right
   questions.
6. Who reviews and approves — is "David + designated DBA reviewers" a
   real, staffed rota? Reviewer capacity bounds how many proposals the
   bot should be allowed to open.
