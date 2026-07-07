# DBA Agent — Security threat model & adversarial review

> Produced 2026-07-07 from four independent adversarial reviews (CI/
> credential/network, DB privilege model, and two LLM/prompt-injection
> passes) against spec v0.2 and the apply-path security model. This is a
> **design-stage** review — no code exists yet, so every finding is a
> gap to close in the spec/tasks before it is built, which is the cheap
> time to close them.
>
> **Bottom line:** the *SQL-execution* containment (template re-render +
> in-DB capped procedures) is a genuinely strong idea and worth keeping.
> But three whole surfaces around it are under-designed: (1) the GitLab
> gate relies on controls that **require Premium while the spec commits
> to Free**, (2) the **read path** is far less guarded than the write
> path yet holds instance-wide secrets, and (3) every *decision* feeding
> the write path is made by an **LLM reading untrusted channel text**
> with no stated injection defenses. Readiness verdict in §5.

## 1. Trust boundaries (make these explicit — the spec did not)

State these in the spec as first-class assumptions:

- **T1 — The alerts Slack channel is untrusted.** Any workspace member
  or any integration/webhook that can post is, for threat-model
  purposes, an attacker. Channel membership is not authorization.
- **T2 — All text captured from a database is untrusted.** Query text
  (`pg_stat_statements`, `v$sql`), object names, error strings can be
  authored by any low-privilege user on a monitored DB and flow into the
  agent's LLM prompt (second-order injection).
- **T3 — DBAs are trusted; service accounts are not.** The model
  contains a compromised applier, a compromised agent, and a leaked
  service credential. It does **not** (and on Oracle SE **cannot**,
  see F-DB10) contain a rogue DBA.
- **T4 — Only three things are trusted inputs:** DBA-reviewed playbooks,
  DBA-reviewed catalogue templates/procedures, and hard-coded tool
  allowlists. Everything else is data, never instructions.

The write path already embodies T4. The read/LLM path does not yet —
that gap is the theme of §3.

## 2. Critical findings (fix before any production wiring)

### C1 — On GitLab Free, the "two human gates" collapse toward one
*(CI review F1/F2/F5)* Several load-bearing controls are **Premium-only**,
but the spec commits to Free (§5.2):
- Restricting *who* can run the manual `apply` job needs Protected
  Environments (Premium). On Free, **any Developer can click apply** on
  a merged, credentialled pipeline. Gate 2 is not DBA-restricted.
- "Remove approvals on new push" is a Premium approval rule. On Free,
  an attacker force-pushes a new commit to the (unprotected) MR branch
  *after* the DBA reviewed it; the byte-match re-render still passes
  because it re-renders the *swapped* params → **the reviewed content is
  not what merges/runs** (TOCTOU).
- Protected **tags** and the separate "Allowed to push" list on `main`
  are unaddressed; either left at defaults bypasses the merge gate
  entirely and still reaches a credentialled protected pipeline.

**Resolution options:** (a) buy Premium and use Protected Environments +
approval rules + CODEOWNERS; or (b) move the apply trigger off GitLab
job permissions — apply runs only on a **protected tag only DBAs can
create**, `main` set to push=no-one/merge-only, MR branches namespaced
so the applier pins and verifies the approved SHA. Either way this must
be settled before prod. **This is the single biggest gap.**

### C2 — A prod-network runner running untrusted pipelines = RCE next to prod DBs
*(CI review F3)* The apply runner is deliberately inside the network zone
that can reach prod DBs. If it also accepts MR/feature/fork pipelines,
anyone who can open an MR gets **code execution on a host with a route to
production** — no credential needed; the network position is the prize.
**Resolution:** dedicated runner, protected-ref pipelines only, untagged
jobs off, egress firewalled to the one target host:port; all pre-merge
pipelines routed to a throwaway runner with no route to prod.

### C3 — Oracle read account leaks every password hash in the instance
*(DB review F1)* `dba_agent_ro` is granted `SELECT ANY DICTIONARY` **in
addition to** `SELECT_CATALOG_ROLE`. `SELECT ANY DICTIONARY` reads
SYS base tables — **`SYS.USER$`** (password verifiers for *every*
account incl. SYS/DBAs), `SYS.LINK$` (DB-link creds), `SYS.SOURCE$`
(all PL/SQL source). This is the always-on, most-exposed credential in
the system. **Resolution: drop `SELECT ANY DICTIONARY` entirely** —
`SELECT_CATALOG_ROLE` is sufficient for monitoring and deliberately
excludes `USER$`. Grant `SELECT` on specific views if a gap appears.
*(Fixed in the spec/security-model docs in this same change.)*

### C4 — The write target is chosen by an LLM from untrusted text, and nothing binds it to the alert's real source
*(LLM reviews F1/F3; CI T1)* The classifier extracts `host` from
attacker-influenceable text; the action `target` is drafted by the
agent. The apply-time preflight only checks `connected_db ==
registry(target)` — it does **not** check `target == the DB the alert
actually came from`. So an injected alert that names a valid-but-wrong
higher-value DB (`boproddb-prod`) passes every check and a real (capped)
DDL runs against the wrong production system. Root enabler: **no
authentication of alert sources** (T1) — anyone in the channel supplies
classifier input. **Resolution:** allowlist alert-source identities;
derive `target` from a trusted, source-set field (prefer a signed
Check_MK webhook for anything that can reach the write path); make
"alert-source host ≠ action target" a hard applier refusal; tier
registry endpoints and require a second approver when an action's
target tier exceeds the alert source's.

## 3. High-severity findings

**Write path / GitLab (CI review):**
- **H1 (F4):** one repo + one merge gate governs CI config, applier
  code, catalogue *templates* (the only executable SQL), `provisioning/`
  *and* action files. Nothing enforces "this MR touches only
  `actions/pending/`." The "just a parameter review" framing trains
  reviewers to skim exactly the MRs that could rewrite the executable
  template or disable the re-render check. **Fix:** CI job that fails any
  pipeline whose diff leaves `actions/pending/` without a separate,
  loudly-labelled approval; split executable surface into a
  stricter-controlled project from the high-volume action-file repo.
- **H2 (F6):** CI variables inject into every job unless
  environment-scoped → one apply job/runner can see **every** DB's
  credential, not just its target's. **Fix:** environment-scope each
  `DBA_APPLY_*` var and bind each job to exactly its environment; grep
  test proving other DBs' creds are absent.
- **H3 (F7):** the agent's GitLab token ("open MR, not merge") in
  practice needs Developer role — which can push to unprotected
  branches (enables C1's swap), trigger manual jobs (enables C1's
  apply), and download protected artifacts (harvest leaked creds). **Fix:**
  narrowest real capability (bot user, API-create-MR only, no push to
  review-bearing branches), short TTL, and prove it can't run a manual
  job or read protected artifacts.
- **H4 (F8):** Layer 3 (in-DB procedures) is explicitly *deferrable* to
  post-v2.0, so the strongest control is absent in the greenest phase
  while the apply account holds real `ALTER TABLESPACE`. **Fix:** no prod
  apply for any action type until its Layer-3 procedure exists; go-live
  checklist refuses `enforcement: scoped-grant` for prod targets.

**DB privilege model (DB review):**
- **H5 (F2/F3):** the read path leaks PII the write path never touches.
  A leaked RO credential reads raw `V$SQL_BIND_CAPTURE`/`v$sql`/
  `pg_stat_activity.query` (literals, not normalized) directly, bypassing
  app-layer redaction; and `pg_read_all_stats`/`SELECT_CATALOG_ROLE`
  expose **`pg_stats` MCVs / histogram endpoints** — *actual sampled
  column values*, so "no table-data grants" is false. **Fix:** treat
  redaction as defense-in-depth only; harden and network-scope the RO
  credential like the apply one; narrow stats-view access; document that
  a leaked RO cred = raw PII read.
- **H6 (F5):** `add_datafile` caps one call at 32G but has **no
  file-count or aggregate cap** — a compromised applier loops it and
  fills the shared filesystem → instance outage. The residual-risk claim
  ("worst case: 8G to the wrong tablespace") understates this. **Fix:**
  enforce max-files and max-total-GB per tablespace *inside* the
  procedure against `dba_data_files`, plus rate limiting and cumulative
  audit.
- **H7 (F6):** the worked Oracle package **cannot compile as written** —
  roles (incl. `SELECT_CATALOG_ROLE`) are disabled inside definer's-
  rights PL/SQL, so the owner can't read `dba_tablespaces`; the tempting
  "fix" (`GRANT SELECT ANY DICTIONARY TO owner`) re-introduces C3 on an
  account that also holds `ALTER TABLESPACE`. **Fix:** direct object
  grant `SELECT ON SYS.DBA_TABLESPACES TO owner`; negative test that the
  owner cannot read `USER$`. *(Fixed in the worked example in this
  change.)*
- **H8 (F7):** VACUUM and `CREATE INDEX CONCURRENTLY` can't run in a
  function, so they fall back to direct grants on the apply account —
  **no Layer-3 protection**, and the `pg_maintain` *role* grants MAINTAIN
  on every table (VACUUM FULL/CLUSTER/REINDEX/LOCK/REFRESH = lock+rewrite
  DoS). **Fix:** per-table `GRANT MAINTAIN ON <table>` never the role;
  scope CIC's `CREATE` to a throwaway schema; forbid `VACUUM FULL`/
  `CLUSTER` action types; state plainly these actions lack Layer 3.
- **H9 (F4):** PG role-level `statement_timeout`/`lock_timeout` are
  session-overridable *defaults*, not caps — a compromised applier does
  `SET statement_timeout=0`. **Fix:** set `lock_timeout` *inside* the
  `SECURITY DEFINER` procedure (runs as owner, caller can't override);
  rely on `CONNECTION LIMIT` + pg_hba as the only hard role controls.

**LLM / agent (LLM reviews):**
- **H10 (F2):** prompt injection via captured DB text (object names,
  SQL comments, error strings) — second-order, laundered through the
  "trusted" read path — can steer classification, severity, diagnosis,
  and (v2) action drafting. **Fix:** delimit and label all DB/alert text
  as untrusted data in prompts, never in the instruction region;
  redact/neutralize *before* the LLM call; constrain outputs to closed
  enums + registry-resolvable host; adversarial test corpus (H14).
- **H11 (F4/F5 LLM):** apply-time preconditions are only meaningful if
  **catalogue-fixed and bound to the action's own params** — if the LLM
  authors the precondition or it targets a different object than the
  action, the "re-checked at apply time" guarantee is theater. Injection
  can also *suppress* real incidents (class-launder to `unknown`,
  downgrade severity, or pre-seed a colliding fingerprint to force a real
  CRITICAL into cooldown). **Fix:** preconditions fixed by catalogue and
  re-rendered like SQL; enforce precondition-object == param-object;
  fingerprint must include a trusted non-LLM field; never fully silence
  high severity — always leave a minimal trace.
- **H12 (F7 LLM):** the ultimate control — a human approving the MR — is
  eroded by design: 63% channel noise primes fatigue, authoritative AI
  prose raises approval of bad items, and **`rendered_sql` (the field a
  reviewer naturally reads) is explicitly never executed** while
  `target`/`params` (what actually matter) are easy to gloss; both
  "gates" are the same DBA group. **Fix:** foreground `target`
  (+ environment/tier) and `params` in the MR, de-emphasize/label
  `rendered_sql` as non-executed, require the approver to positively
  confirm the target, second approver for prod-tier, track approval-rate
  as a fatigue metric.

## 4. Medium / lower findings (close before the relevant phase)

- **M1 (DB F8):** the applier can tamper with its own `dba_agent_audit`
  table. Make it **append-only** (INSERT only, event-sourced) or write it
  inside the definer's procedure; designate engine-native audit as the
  sole source of truth.
- **M2 (DB F9):** Oracle unified-audit `BY dba_agent_apply` may miss the
  `ALTER TABLESPACE` that actually executes as the *definer*. Add an
  action-scoped policy and assert the DDL (not just the EXECUTE) is
  captured.
- **M3 (DB F13):** the RO account is unhardened (no connection limit,
  timeouts, pg_hba scoping) though it runs 24/7 — connection-exhaustion
  and idle-in-transaction xmin-pinning DoS. Harden like the apply account.
- **M4 (DB F12):** allowlist *tables* are DB data; adding a row expands
  scope with no git review. Provision allowlist contents from
  `provisioning/`; forbid ad-hoc DML; audit inserts.
- **M5 (DB F11):** Oracle owner holds unnecessary `CREATE SESSION` beside
  `ALTER TABLESPACE`. Drop it; verify the owner cannot authenticate.
- **M6 (CI F9/F10/F11):** GitLab masking is best-effort log redaction,
  not a secrets boundary (applier must never log DSN/errors); mandate
  ephemeral executor + digest-pinned applier image; scope
  `CI_JOB_TOKEN` allowlist to minimum.
- **M7 (CI F12):** the long-lived agent concentrates every secret
  (all-DB read creds, Anthropic, Slack, Check_MK, GitLab token) on one
  box whose whole job is ingesting hostile input. Split secrets by blast
  radius; move MR-creation behind a separate minimally-scoped service;
  fetch read creds per-query from a vault with short TTL.
- **M8 (CI F13 / DB):** playbook parameters from alert text must be
  **bind variables**, never string-interpolated — else read-path SQL
  injection under the RO identity (which on Oracle reaches the
  dictionary). Reject any playbook that interpolates.
- **M9 (LLM F8/F9):** budget/MR-spam DoS keyed off attacker input —
  per-source rate limits, degrade-to-queue not silent-drop, cap
  agent-opened MRs/window. `gather_stats` can flip prod plans within
  caps — mark irreversible, allowlist targets, second-approver class.
- **M10 (LLM F6/F11):** state a **data-classification decision** for what
  DB content may leave to the Anthropic API (query literals are the
  highest-risk field); constrain Check_MK lookups to the
  provenance-resolved host to prevent cross-host recon; render evidence
  as inert text (no Slack mrkdwn/link injection).

- **H14 / meta (LLM F10):** the classifier's only quality bar is "100% on
  ~20 benign messages" — **no adversarial/injection corpus anywhere.**
  Add a red-team corpus (crafted object names, SQL-comment injection,
  host/severity steering, fingerprint collisions, second-order DB-text
  injection) as a required gate measuring "refuses to be steered," not
  "labels benign inputs correctly." This is how the whole C4/H10/H11
  class ships undetected otherwise.

## 5. Readiness verdict

**Are we ready to implement? Split the answer by phase.**

- **The POC (containers only): yes, build it now.** Every finding above
  is about *production* wiring — real credentials, real networks, real
  channel, the real apply path. The POC runs entirely in the local
  compose stack against throwaway databases with no production reach, so
  it carries none of this risk and is the right place to build the loop
  and *rehearse the negative tests*. Proceed with `tasks/foundation/
  agent-skeleton.md`. Two things to bake in from the first line of code
  because they're cheap now and expensive later: **T2/T4 untrusted-data
  discipline** in every prompt (delimit DB/alert text, closed-enum
  outputs, bind-variable-only playbooks) and the **alert-source
  allowlist** (C4/T1) in the listener.

- **Production wiring (v1 read path): not yet — but close.** Before the
  agent touches a real DB read-only, resolve C3 (drop `SELECT ANY
  DICTIONARY`), H5/M3 (harden + network-scope + document the RO
  credential's real reach), M7 (don't concentrate all secrets on the
  hostile-input box), M8 (bind variables), and M10 (data-classification
  decision for API egress). These are days of work, not weeks.

- **Production apply path (v2 write): no. Do not build the applier
  against prod until the GitLab-tier question (C1) and the runner
  isolation (C2) are settled** — those two invalidate the headline
  "two gates" claim on the currently-chosen tier, and no amount of DB
  procedure hardening compensates for a gate that a non-DBA can open.
  Then land H1–H9, H11–H12, M1–M2, M4–M6, M9. The DB-procedure idea is
  sound; the worked examples had two real defects (H7 compile bug, C3
  over-grant) now fixed, which is exactly why "review before build" was
  worth doing.

**What we're not seeing that this review surfaced most sharply:** the
design poured its rigor into the *last* link (what SQL executes) and left
the *first* links thin — who is allowed to speak to the agent (T1/C4),
what the always-on read credential can actually reach (C3/H5), whether
the chosen GitLab tier can enforce the gate at all (C1), and whether the
human at the end can realistically catch a bad change (H12). A chain is
as strong as its weakest link, and the weakest links are upstream of the
part we hardened.

## 6. Where each finding is tracked

- Concrete doc fixes applied now: C3 and H7 in
  `apply-path-security-model.md` and spec §6.
- Everything else: `tasks/security/threat-model-remediation.md`, split
  into POC-era (untrusted-data discipline, source allowlist,
  bind-variables, adversarial corpus) and pre-prod gates (GitLab tier,
  runner isolation, RO hardening, procedure aggregate caps, audit
  independence). Production wiring is blocked on those gates via the
  go-live checklist in `apply-path-security-model.md` §6.
