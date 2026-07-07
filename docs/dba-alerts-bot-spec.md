# AI-Assisted Postgres + Oracle Operations — System Spec

> Status: **superseded** by `dba-agent-spec.md` (v0.2). Kept for history;
> the adversarial review that led to the rewrite is
> `dba-alerts-bot-spec-review.md`, and the decision log is
> `dba-agent-direction.md`.

## 1. Purpose

Build a system where AI assists DBA operations across Postgres and Oracle by:
reading telemetry and DB state, identifying non-optimal conditions or reacting
to alerts, and proposing changes as reviewable, auditable artifacts. AI never
writes to production directly. All writes flow through GitLab merge requests
(the approval gate) and a governed CI pipeline (the applier), using sqitch for
change tracking, deploy, revert, and verification.

## 2. Goals

* Reduce time-to-diagnosis when a DB alert fires (RCA assist).
* Surface non-obvious optimisation opportunities (indexes, stale stats, bloat,
  stuck grants) that wouldn't get regular attention.
* Make every DB change — DDL, DCL, or DBA-operational — go through the same
  reviewed, audited, revertible path, whether authored by a human or proposed
  by AI.
* Reuse existing infrastructure: GitLab (repo, MR, CI), Foundry (hosting),
  Slack (interface), Prometheus/Grafana (telemetry).
* Strictly open-source tooling for every new component.

## 3. Non-goals (explicitly out of scope for v1)

* Autonomous application of changes to production without human approval.
* Full DBA replacement or "AI manages everything."
* Managing anything beyond Postgres and Oracle (no MySQL/SQL Server/etc.).
* Real-time streaming remediation (sub-second reaction). Alert-to-proposal
  latency of minutes is acceptable.
* A GUI beyond Slack and GitLab. No new dashboard product.

## 4. Assumptions to confirm with stakeholders

1. Oracle is self-managed (not Autonomous Database) — confirm, as this
   determines the tool layer (SQLcl MCP + oracle-db-skills vs. Oracle's
   managed MCP/Select AI).
2. AWR/ASH licensing (Diagnostics Pack) status on Oracle — determines whether
   we use AWR or fall back to Statspack + `v$` views.
3. Foundry (the K8s hosting platform) can run long-lived containers with a
   network path to prod DBs (read-only) and to a CI runner with a separate
   path for the migration identity.
4. GitLab CI runners can reach the Foundry network segment hosting the DBs,
   or a runner can be placed on Foundry itself with GitLab runner
   registration.
5. There are two identities per DB, provisioned separately:
   * Read-only agent identity: `pg_monitor` (+ `pg_read_all_stats`,
     `pg_read_all_settings`) on Postgres; `SELECT_CATALOG_ROLE` +
     `SELECT ANY DICTIONARY` + explicit `v$`/`gv$` grants on Oracle. No DML,
     no DDL, no DCL.
   * Migration/DCL identity: capable of DDL, DML for stats/config tables, and
     DCL (`GRANT`/`REVOKE`, role management) — scoped as tightly as the actual
     change catalogue requires, not blanket superuser. Used only by the CI
     runner, never by the agent.

## 5. Architecture overview

```
Slack  <──alerts/reports/MR-links──>  Custom App (Foundry)  <──MCP, read-only──>  Postgres / Oracle
                                              │
                                              │ writes sqitch change files, opens MR
                                              ▼
                                        GitLab repo (sqitch project)
                                              │
                                              │ MR review + approval (David / DBA sign-off) — THE gate
                                              ▼
                                        GitLab CI pipeline
                                              │
                                    stage: sqitch deploy → staging (auto)
                                    stage: sqitch verify (auto)
                                    stage: sqitch deploy → prod (MANUAL approval click)
                                    stage: sqitch verify → prod, report to Slack
                                              │
                                              ▼ (migration identity, DDL/DCL-capable)
                                        Postgres / Oracle (writes)
```

## 6. Components

### 6.1 Custom App ("the agent") — new build, hosted on Foundry

Responsibilities:

* Ingest: subscribe to existing Slack alert channel(s); also run on a schedule
  (e.g. daily/weekly health-check cadence, not real-time).
* Context gathering: query Prometheus/Grafana for metrics history; query the
  DB read-only via MCP tools for current state (slow queries, index usage,
  stats freshness, tablespace usage, grants).
* Reasoning: call Claude with the gathered context plus a playbook (a fixed
  set of diagnostic procedures per alert type, to constrain behaviour and
  reduce hallucination — mirroring the pattern used by tools like Xata's
  open-source agent).
* Output — advisory: for read-only findings, post a structured report to
  Slack (what's wrong, evidence, suggested fix in words).
* Output — proposal: for anything requiring a DB write, generate a sqitch
  change (deploy/revert/verify SQL triplet), commit to a branch, open a GitLab
  MR with the AI's reasoning in the description, and post the MR link to
  Slack.
* Guardrails: hard-coded denylist of operation types that must never be
  auto-proposed without explicit human request (e.g. `DROP TABLESPACE`,
  `DROP USER` with dependent objects); flag irreversible operations
  explicitly in the MR description and in the revert script itself.

Tech shape: language/framework open, but if Python + SQLAlchemy is the natural
fit for the app's own bookkeeping, note that this does not imply using Alembic
for the target databases — the app emits raw sqitch SQL, not ORM migrations,
precisely because DCL/DBA operations don't fit a table-model diffing tool.

### 6.2 Read-only tool layer (MCP)

* Postgres MCP Pro (`crystaldba/postgres-mcp`), restricted mode, bound to the
  `pg_monitor`-based role. Provides EXPLAIN/HypoPG-based index analysis,
  health checks, safe read queries.
* SQLcl MCP Server (bundled with Oracle SQLcl 25.2+), restrict level set to
  most restrictive, bound to the `SELECT_CATALOG_ROLE`-based user. Logs to
  `DBTOOLS$MCP_LOG`; tags sessions via `V$SESSION.MODULE/ACTION`.
* Optional: subset of Oracle's `oracle-db-skills` (or equivalent hand-built PG
  skill set) loaded per task to give the agent correct engine-specific query
  patterns.

### 6.3 Telemetry

* Postgres: `pg_stat_statements` + `hypopg` extension enabled;
  `postgres_exporter` (Apache-2.0) → Prometheus → Grafana. (Finish the
  partially-wired instance.)
* Oracle: `oracle/oracle-db-appdev-monitoring` exporter (official, OSS) with
  custom TOML metrics for tablespace usage, session waits, top SQL →
  Prometheus → Grafana.
* Grafana dashboards imported from community/official prebuilt sets rather
  than built from scratch.

### 6.4 Change management (governance + apply)

* sqitch (MIT), one project per database target (or a shared repo with `pg/`
  and `oracle/` subprojects), each change as a deploy/revert/verify SQL
  triplet.
* Registry tables (sqitch-managed) live inside each target database, tracking
  what has been applied.
* GitLab as the sole orchestration layer: protected `main` branch, required MR
  approvers (David + designated DBA reviewers), CI pipeline as described in
  §6.5. No additional platform (e.g. Bytebase) introduced.

### 6.5 GitLab CI pipeline (per merge to main)

1. Lint / dry-run stage (on MR, pre-merge): `sqitch deploy --to-target`
   against a disposable/staging copy, or at minimum a syntax/connection check;
   surface the diff in the MR for the reviewer.
2. Deploy to staging (auto, on merge): `sqitch deploy` against the staging
   Postgres/Oracle instance.
3. Verify staging (auto): `sqitch verify`.
4. Deploy to prod (manual gate): a GitLab manual pipeline job — a human
   clicks "run" after confirming staging looked correct. This is the second,
   physical gate on top of MR approval.
5. Verify prod (auto, immediately following): `sqitch verify`; on failure,
   alert Slack immediately and halt (do not auto-revert without human
   sign-off, given Oracle's non-transactional DDL).
6. Report: post outcome (success/failure, change summary) back to the
   originating Slack thread.

Runner requirements: network path to both staging and prod DB segments;
Oracle Instant Client + Perl `DBD::Oracle` baked into the runner image for
sqitch's Oracle engine support; migration identity credentials injected as
protected/masked CI variables or pulled from a vault at runtime, never stored
in the repo.

## 7. Security model

* Two-identity separation (read vs. migration) is a hard requirement,
  enforced at the DB grant level, not just convention.
* All AI-authored SQL is human-reviewed before merge; no bypass path.
* Irreversible operations (datafile additions, user drops with dependent
  objects, etc.) must have a revert script that explicitly fails with a clear
  message rather than a no-op, and must be flagged in the MR description by
  the agent.
* Audit trail is layered: GitLab MR history (who approved what), sqitch
  registry (what was deployed when), SQLcl MCP log / Postgres MCP query log
  (what the agent read), CI pipeline log (what the runner executed).
* Secrets (DB credentials for both identities) via GitLab CI protected
  variables or an existing secrets manager if Foundry has one — not
  hardcoded.

## 8. Phased delivery (dependency-ordered, not time-ordered)

* Phase 0 — Telemetry: finish `postgres_exporter` wiring; stand up Oracle
  exporter; both into existing Prometheus/Grafana; create both DB identities
  on dev/staging.
* Phase 1 — Read-only advisory: MCP tool layer + agent's reasoning path;
  Slack report output only; no write path exists yet.
* Phase 2 — Governed change proposals: sqitch project scaffolding; GitLab CI
  pipeline (staging auto, prod manual); agent gains the "write a sqitch
  change + open MR" capability, scoped initially to a narrow, reversible
  operation set (e.g. index creation, stats gathering, simple grants).
* Phase 3 — Alert-driven RCA: wire existing Slack alerts as a trigger into
  the agent; add playbooks per alert type.
* Phase 4 (later, optional) — narrow, whitelisted auto-apply for the
  lowest-risk reversible operations only, still fully audited, still
  excluding anything irreversible or DCL-sensitive.

## 9. Open decisions requiring input

* Oracle hosting model (self-managed vs. Autonomous) — confirm before
  finalising Oracle tool layer.
* AWR/ASH licensing status.
* Where exactly the GitLab CI runner with prod DB network access will live,
  and how its credentials are managed (existing vault vs. new setup).
* Initial whitelist of operation types the agent is allowed to propose in
  Phase 2 (recommend starting with: index creation/drop,
  `ANALYZE`/`DBMS_STATS`, simple `GRANT`/`REVOKE` on non-sensitive objects —
  explicitly excluding tablespace/datafile/user-drop operations until trust
  is established).

## 10. Modular connector architecture (ports & adapters)

The design principle: the agent core is engine-agnostic and depends only on a
small set of interfaces (ports). Every external dependency has interchangeable
adapters — at minimum a mock adapter and a live adapter — selected at runtime
by configuration. This is what makes the system testable, incrementally
de-riskable, and open to new engines (including QuestDB) without touching the
core.

Four ports:

1. **DBConnectorPort** — how the agent inspects a database and validates
   proposed SQL. Contract (illustrative): `inspect(scope)`,
   `analyze(query|object)`, `validate(sql)`. Adapters:
   * Postgres → Postgres MCP Pro (restricted).
   * Oracle → SQLcl MCP (restrict level high).
   * QuestDB → an adapter that wraps existing in-house QuestDB tooling and
     exposes it through the same contract, ideally as an MCP server so it is
     protocol-identical to the others. sqitch and Postgres MCP Pro do not
     cover QuestDB; the in-house runner remains the applier/reasoner
     underneath, behind this port.
   * Mock → returns canned inspection results / validation verdicts for
     deterministic tests.
2. **LLMPort** — the reasoning call. Live adapter → Anthropic API (Claude).
   Mock adapter → fixed/scripted responses for deterministic tests. Isolating
   this makes test runs free, fast, and non-flaky, and keeps the API key out
   of most test paths.
3. **ProposalPort** — how a change becomes a reviewable artifact. Live
   adapter → writes sqitch deploy/revert/verify files, commits a branch,
   opens a GitLab MR. Mock adapter → writes the files to a local dir and
   records "would have opened MR X" for assertion.
4. **NotifierPort** (Slack) — inbound alerts/triggers and outbound
   reports/MR links. Live adapter → Slack (Events API / webhook). Mock
   adapter → in-memory fake (recommended default for tests) or, for
   black-box HTTP-level integration tests, `slack-mock` (Node, dated — treat
   as optional harness, not a core dependency; if the agent is not Node,
   point the Slack SDK `base_url` at it).

Rule: the agent core imports only the port interfaces. No adapter imports
another adapter. Adding an engine = writing one DBConnectorPort adapter;
swapping mock↔live = one config flag.

## 11. Containerised POC

### 11.1 One container or several?

* Fully-mocked logic smoke test — a single container is appropriate: the
  agent running with all four ports bound to mock adapters, no external
  calls. Hermetic, fast, runs in CI. This is the true "v0" and proves the
  orchestration (listen → reason → propose) end-to-end with zero
  infrastructure.
* Integration POC (live connectors) — use `docker-compose` with isolated
  services. Cramming a live database, the agent, and mocks into one container
  contradicts the modularity goal, loses state on restart, and prevents
  swapping pieces independently. A single all-in-one container is a
  smoke-test convenience, never the target architecture.

### 11.2 docker-compose topology (integration POC)

```
services:
  agent          # the custom app: bot listener + reasoning loop (the only long-lived service we build)
  postgres       # real postgres:16, pg_stat_statements preloaded, seeded with a deliberately slow query / missing index
  postgres-mcp   # Postgres MCP Pro (restricted) — OR run as stdio subprocess inside `agent`
  slack-mock     # optional: black-box Slack HTTP interception (else use in-memory NotifierPort fake)
  # gitlab: use a throwaway real GitLab test project, or bind ProposalPort to its mock adapter
  # prometheus/grafana: OUT of the POC — the agent reads the DB directly via DBConnectorPort; telemetry is Phase 0 infra, not needed to prove the loop
```

Notes:

* Oracle is not run in the POC. A local Oracle container is heavyweight and
  licensing-encumbered; the Oracle DBConnectorPort stays on its mock adapter
  until a real dev instance is available. The POC proves the loop on
  Postgres, which runs trivially in Docker.
* MCP transport choice determines container count: stdio MCP servers (SQLcl;
  optionally Postgres MCP Pro) run as subprocesses inside the agent
  container; HTTP/SSE MCP servers run as their own containers and are
  swapped by URL. HTTP is cleaner for the "interchangeable" goal; stdio is
  fewer moving parts for v0.
* Secrets (Anthropic key, DB creds, GitLab token) injected via env/compose
  secrets at runtime, never baked into images, masked in logs.

### 11.3 How we arrive at the POC (incremental adapter-swap sequence)

Each step flips exactly one port from mock to live, so a failure localises to
one boundary:

1. All mocked, one container. Prove the orchestration loop deterministically.
   Runs in CI.
2. Live DBConnectorPort → seeded Postgres. Prove the agent reads real DB
   state and produces a real index/stats finding.
3. Live LLMPort → Anthropic API. Prove Claude's reasoning/output quality on
   the real finding.
4. Live ProposalPort → throwaway GitLab project. Prove a real MR is opened
   containing valid sqitch deploy/revert/verify files.
5. Live NotifierPort → Slack (or slack-mock). Prove the full round trip:
   trigger in, MR link + report out.
6. Prove `sqitch revert` on the created change against a scratch Postgres —
   the step most POCs skip and regret.

The demoable POC target: a seeded slow query → agent detects missing index
via live Postgres MCP → Claude explains it → sqitch triplet written → real MR
opened → (manual) merge → CI applies to the POC Postgres → verify confirms
plan improved → Slack notified. One engine, one scenario, manual trigger,
full loop.

## 12. Testing strategy

* Deterministic core tests: all ports mocked; assert the agent's decision
  logic (advisory vs. proposal, correct sqitch files emitted,
  idempotency/dedup behaviour) with zero external calls.
* Contract tests per adapter: each live adapter tested against its real
  dependency in isolation (does Postgres MCP return what DBConnectorPort
  expects; does ProposalPort actually open an MR).
* Integration test: the compose stack with selected ports live, driven by an
  injected alert, asserting the MR is created and Slack notified.
* Live-connector toggles: a single env matrix (`MOCK` / `LIVE` per port) lets
  the same test suite run fully-mocked in CI and selectively-live on demand.

## 13. Failure paths to design for

* LLM emits invalid or dangerous SQL (hallucinated column/table, destructive
  statement): mitigate by validating generated SQL through DBConnectorPort
  against the real schema (and a dry-run on staging) before opening the MR;
  hard-denylist destructive/irreversible statements; the human MR review is
  the final catch, never the only one.
* Slack event retries / duplicates: Slack redelivers if not acked within ~3s.
  The listener must ack immediately and process asynchronously, and
  de-duplicate on Slack event ID (idempotency key) so one alert never
  produces multiple MRs.
* Runaway proposals / MR spam: dedupe on finding-identity ("already have an
  open MR for this index") and apply a proposal rate-limit/budget, so a
  flapping alert can't open dozens of MRs.
* stdio MCP subprocess hangs or dies: per-call timeouts, health checks, and
  supervised restart; a hung tool call must not hang the agent.
* Read-only boundary bypass: enforce read-only at the database (the agent's
  role has no write grant) — never rely on app logic alone. Migration
  identity is separate and used only by the CI runner.
* Secret leakage: inject at runtime, mask in logs, never bake into images; a
  logged connection string is an incident.
* Agent restart mid-proposal (double-open): persist an in-flight/idempotency
  marker so a crash-and-restart doesn't reopen the same MR.
* Egress from Foundry to `api.anthropic.com`: works locally, may be
  firewalled in Foundry — confirm egress rules early; failure here is a
  silent LLMPort timeout.
* Oracle non-transactional DDL (when Oracle is later added): a half-applied
  multi-statement change cannot be atomically rolled back — keep Oracle
  changes small/atomic, stage first, rely on `verify`; keep Oracle out of any
  auto-apply path.
* All-in-one container coupling: acceptable only for the mocked smoke test;
  for anything with live connectors, isolation prevents a single crash from
  taking down the whole loop and preserves interchangeability.

## 14. Additional open decisions (from this iteration)

* Agent implementation language (affects whether `slack-mock` is usable
  in-process, and stdio-MCP subprocess ergonomics).
* MCP transport per connector: stdio-subprocess vs. HTTP-service (drives
  container count and interchangeability).
* ProposalPort in POC: throwaway real GitLab project vs. mock adapter.
* QuestDB adapter: wrap the in-house tooling as an MCP server
  (protocol-identical, preferred) vs. a thinner REST/adapter shim behind
  DBConnectorPort.
