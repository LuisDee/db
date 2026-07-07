# DBA Agent — System Spec v0.2 (canonical)

> Status: **current**. Supersedes `dba-alerts-bot-spec.md` (v0.1, kept
> for history). Decisions behind every departure from v0.1 are logged in
> `dba-agent-direction.md`; work items live in `tasks/` as a
> Structured-Tasks DAG. Last updated 2026-07-07.

## 1. Purpose and repo intent

This repo builds the **DBA agent**: an AI assistant for database
operations across Postgres, Oracle (Standard Edition), and QuestDB.
It listens to the DBA alerts channel, debugs alerts with read-only
queries, posts evidence-backed diagnoses in-thread, reduces alert
noise, and — behind a DBA-controlled approval gate — proposes and
applies operational changes. It is the foundation for broader agentic
DB work (scheduled health sweeps, alert-coverage design, capacity
forecasting).

The repo contains: the agent application (Python, containerized), its
playbooks and endpoint registry, the runbook-action catalogue and
applier, design docs (`docs/`), and Structured-Tasks work items
(`tasks/`).

## 2. Principles (non-negotiable)

1. **The agent never holds write credentials.** Reads use per-DB
   read-only identities; writes happen only in a post-approval CI job
   under a separate identity.
2. **The LLM never authors diagnostic SQL.** It selects, parameterizes
   and interprets preset, DBA-reviewed queries (playbooks) and action
   templates. (Industry convergence: Xata, HolmesGPT, pganalyze.)
3. **No SSH.** Host-level facts come from the Check_MK API; DB facts
   from read-only SQL. What neither can answer is infra's problem and
   becomes a Jira handoff with evidence.
4. **Noise discipline.** Only playbooked alert classes get replies;
   verdict-first, two lines, detail collapsed; silent when there is
   nothing to add; cooldown per alert fingerprint.
5. **Containers-first.** The full loop must pass in the local compose
   stack (`tasks/poc/e2e-demo.md`) before any real host, credential, or
   channel is touched.
6. **License-clean Oracle.** Standard Edition: no AWR/ASH/`dba_hist_*`
   (Diagnostics Pack is EE-only); base `v$`/`dba_` views and Statspack
   only. No Data Guard assumptions.
7. **Open-source tooling only** for new components.

## 3. System at a glance

```
                 alerts (Check_MK & friends → Slack channel)
                                   │
Slack ◄──threaded diagnosis────┐   ▼
  ▲                            │  listener (Socket Mode, ack+dedup)
  │ weekly noise digest        │   │
  │ sweep findings             │   ▼
  │                            │  classifier (LLM) → {class, host, fingerprint}
  │                            │   │
  │                            │   ▼
  │                            │  endpoint registry (host → engine, DSN, ro-cred ref)
  │                            │   │
  │                            │   ▼
  │                            └─ playbook executor ──read-only SQL──► PG / Oracle / QuestDB
  │                                │        └────────Check_MK API───► host facts
  │                                ▼
  │                          evidence bundle → LLM synthesis
  │                                │
  └────────────────────────────────┤
                                   ▼ (when a write or infra action is warranted)
                     GitLab MR: runbook-action file (target, params, rendered SQL)
                                   │  merge permission = DBA group (THE gate)
                                   ▼
                     manual "apply" CI job (second gate, human click)
                                   │
                                   ▼
                     applier (in runner) ──preflight → execute → audit──► target DB
                                   │
                                   └── outcome → audit table + job artifact + Slack thread
```

Three delivery surfaces share the same machinery:
- **Triage** (alert-driven): the loop above.
- **Noise digest** (weekly batch): classify 7 days of channel history,
  post counts, flaps, suppression suggestions.
- **Scheduled sweep** (post-POC): playbooks run on a timer instead of an
  alert — datafile/tablespace headroom, growth forecasts, missing-alert
  suggestions — findings posted as a digest, remediations proposed
  through the same MR path.

## 4. Read path (triage) — components

- **Listener** — Slack Bolt, Socket Mode (no public ingress). Ack
  immediately, process async, dedup on `event_id`, persist across
  restarts. Captures bot/webhook-authored messages (alerts are posted
  by other bots). Reactions (👍/👎) on agent replies are captured as the
  usefulness metric.
- **Classifier** — LLM parses raw alert text into
  `{alert_class, host/db, severity, fingerprint}`. The LLM is the
  parser because sources are heterogeneous. Golden-corpus tested against
  real (anonymised) alert messages.
- **Endpoint registry** — YAML: endpoint key → engine, DSN, environment
  tag, read-only credential ref (env-resolved; no secrets in the file),
  aliases. Unknown host is a first-class outcome, not a guess.
- **Playbooks** — YAML metadata + preset read-only SQL per engine +
  interpretation notes, DBA-reviewed in git. POC set: filesystem
  disk-space, standby replication lag, tablespace usage. Executor runs
  under the read-only identity with per-query timeouts; literals in any
  captured SQL text are redacted before leaving the agent (PII).
- **Synthesis** — LLM turns the evidence bundle into the threaded
  reply: two-line verdict, evidence, suggested action, Jira draft when
  the fix is infra-owned. Confidence comes from corroborating evidence,
  never from asking the model. Every diagnosis is persisted with its
  eventual reactions.
- **Dedup/cooldown** — per-fingerprint cooldown window; repeats update
  a counter on the existing thread at most. Per-day LLM budget. An
  alert storm is neither an MR storm nor a token storm.

## 5. Write path — runbook actions via GitLab

There is no migration tool (sqitch dropped — see direction doc §1) and
no "write API": for PG and Oracle a write is SQL over a connection
regardless of tooling. The design question is *who holds the write
credential and when it can fire*. Answer: never the agent; only the
applier, inside a post-approval CI job.

### 5.1 The artifact: a runbook-action file

The agent (or a human) opens an MR adding one file under
`actions/pending/`, e.g.:

```yaml
action: add_datafile            # must exist in the action catalogue
target: boproddb-prod           # endpoint registry key — THE targeting field
requested_by: dba-agent
alert_thread: slack://C0.../p1751881200
expires: 2026-07-21             # stale actions refuse to apply
params:
  tablespace: USER_INDEX_04
  size: 8G
preconditions:                  # re-checked at apply time, not just review time
  - tablespace_pct_used("USER_INDEX_04") > 85
rendered_sql: |
  ALTER TABLESPACE USER_INDEX_04 ADD DATAFILE SIZE 8G AUTOEXTEND ON NEXT 1G MAXSIZE 32G;
```

The **action catalogue** (`actions/catalogue/`) defines each action
type once: parameter schema, SQL template per engine, allowed
environments, required preconditions, whether a meaningful revert
exists. DBAs review the *template* once; each *invocation* MR is a
parameter review, which is much easier to approve safely than free-form
SQL.

### 5.2 The gate

- Protected `main`; **only the DBA GitLab group has merge permission**.
  This is the approval mechanism and works on GitLab Free (enforced
  approval rules / CODEOWNERS need Premium; merge permission achieves
  the same control). No external group system needed — GitLab group
  membership is the approver list.
- After merge, the pipeline's **apply job is `when: manual`** — a DBA
  clicks it. Two human gates: approve the change, then pull the
  trigger. The job name embeds the target and action
  (`apply: add_datafile → boproddb-prod`) so the click is informed.

### 5.3 The applier and how it reaches the DBs

The applier is a small Python program in the runner image (drivers:
python-oracledb, psycopg; no Instant-Client/Perl stack needed —
python-oracledb thin mode). It does **not** "fire the runbook over the
wire" to something on the DB host — nothing is installed on DB hosts.
It opens a normal SQL connection *from the runner* to the target and
executes statements one at a time. Sequence:

1. **Resolve**: look up `target` in the endpoint registry; write
   credential ref resolves from CI variables/vault. Unknown target →
   hard fail, nothing executed.
2. **Preflight — right database?** Connect and verify identity:
   `SELECT name, db_unique_name FROM v$database` /
   `SELECT current_database(), inet_server_addr()` must match the
   registry entry. Kills the "right SQL, wrong DB" class dead.
3. **Preflight — still needed?** Re-evaluate `preconditions` (the
   world may have changed between MR approval and apply; the alert may
   be stale). Not met → refuse, report, no changes.
4. **Preflight — not expired, not already applied?** Check `expires`
   and the audit table for this action id.
5. **Execute** statement-by-statement, writing a **write-ahead audit
   record** before and a result record after each statement.
6. **Report**: outcome to the audit table, the CI job artifact, and the
   originating Slack thread.

### 5.4 Scaling across many Oracle and PG databases

- **Targeting** scales by registry entry: one repo, one action format,
  N endpoints. Adding a database = registry entry + two service
  accounts + credentials.
- **Network** scales by runner tags: the apply job carries the tag of
  the runner that can reach that DB's segment
  (`tags: [dbnet-uk]` etc.). One runner per network zone, not per DB.
- **Concurrency**: GitLab `resource_group: <target>` on the apply job —
  one apply at a time per endpoint, so two merged actions against the
  same DB serialize.
- **Credentials**: GitLab protected+masked CI variables are fine at POC
  scale; beyond ~a dozen DBs, move to a vault (Foundry's secrets
  manager if one exists) with the runner fetching at job time. Naming
  convention `DBA_APPLY_<ENDPOINT_KEY>` keeps variables auditable
  meanwhile.

### 5.5 Failure routes (write path)

| Failure | Handling |
|---|---|
| Wrong target / registry typo | Preflight identity check (db name must match registry) before any statement |
| World changed since approval | Preconditions re-evaluated at apply time; refuse if not met |
| Stale action applied months later | `expires` field; refuse past expiry |
| Partial apply (Oracle DDL autocommits — no rollback) | Statement-at-a-time with write-ahead audit; halt on first error; report exactly which statement failed; re-run resumes only after the audit shows what landed; never auto-retry blind |
| Connection drop mid-apply | Same as partial apply — the write-ahead record shows the in-flight statement |
| Runner can't reach DB / creds expired | Preflight connect fails fast; zero changes made |
| Two actions racing on one DB | `resource_group` serializes; the second re-runs preconditions |
| DBA clicks the wrong manual job | Job name embeds action + target; one action file per MR keeps jobs unambiguous |
| Revert needed | Catalogue marks reversibility per action type; irreversible actions say so in the MR and their "revert" fails loudly with instructions, never a silent no-op |

## 6. Identities and service accounts

Per target database, two provisioned accounts (creation SQL lives in
this repo under `provisioning/`, reviewed like any change):

| Account | Postgres | Oracle | Used by |
|---|---|---|---|
| `dba_agent_ro` | `pg_monitor` + `pg_read_all_stats` + `pg_read_all_settings`; no table-data grants | `CREATE SESSION`, `SELECT_CATALOG_ROLE`, `SELECT ANY DICTIONARY` | agent (triage, digest, sweep) |
| `dba_agent_apply` | scoped to the action catalogue (e.g. `CREATE` on target schemas) | scoped where possible; tablespace/datafile ops need `ALTER TABLESPACE` etc. — where scoping runs out, auditing covers it (below) | applier (CI job only) |

QuestDB: read via its SQL interface (`table_storage()` etc.) with a
read-only user where the deployment supports it; QuestDB writes are out
of scope for the action catalogue v1.

Plus application-level service accounts: Slack bot token (Socket Mode
app), Anthropic API key, Check_MK API user (read-only), GitLab project
access token (open MRs only — not merge), Jira service account (v1.5).

## 7. Audit model — yes, and it's layered

Production DBs demand it; most layers come free:

1. **Git/MR history** — who proposed, who approved (merged), the full
   diff of exactly what was to run. Immutable.
2. **CI job log + artifact** — the execution transcript, retained per
   GitLab retention policy.
3. **Audit table on each target** (`dba_agent_audit`): action id, MR,
   statement, start/finish, outcome, identity — written by the applier
   around every statement (this doubles as the partial-apply recovery
   record).
4. **Engine-native audit on the apply identity** — Oracle unified
   auditing policy scoped to `dba_agent_apply` (included in SE);
   Postgres `ALTER ROLE dba_agent_apply SET log_statement = 'all'`.
   Enforced by the DB, so it holds even if the applier misbehaves.
5. **Read-path audit** — every diagnosis persisted (alert, evidence,
   queries run, reply, reactions); literal-redaction before anything is
   posted.
6. **Slack thread** — the human-readable trail, linked from the MR and
   the audit record.

## 8. Delivery

- **POC** (current, containers-only): the `tasks/` DAG — skeleton,
  registry, compose stack (postgres:16 + gvenzl/oracle-free + questdb +
  alert injector), listener, classifier, playbook framework, three
  playbooks, synthesis, dedup, noise digest. Exit:
  `tasks/poc/e2e-demo.md`.
- **v1 (plug in)**: real Slack channel + read-only identities on real
  DBs + Check_MK API. Triage on the three playbooks; weekly digest.
- **v1.5**: live Jira creation; @-mention follow-ups bounded to the
  read-only catalogue; feedback metrics dashboarded.
- **v2 (write path)**: action catalogue + applier + GitLab gate as §5
  (`tasks/apply/runbook-apply-path.md`); starts with add-datafile and
  gather-stats.
- **Post-v2**: scheduled sweeps, alert-coverage advisor, capacity
  forecasting reports.

Parallel, mostly-human workstreams the agent assists but doesn't
require code for: suppress the nightly refresh spam; RCA the QuestDB
health flap and the nightly FK warning (one-off fixes that remove ~63%
of channel noise).

## 9. Open questions

1. **boproddb standby mechanism** (Data Guard is EE-only; scripted log
   shipping? Dbvisit?) — blocks the Oracle replication playbook query
   set.
2. Check_MK API availability/version (Livestatus vs REST) and a
   read-only API user.
3. Egress to `api.anthropic.com` from Foundry — verify with the week-0
   spike.
4. Secrets: does Foundry provide a vault, or GitLab CI variables until
   scale demands one?
5. Slack app approval process internally (Socket Mode app creation).
6. Jira project + service account for the infra-handoff path (v1.5).
