---
depends_on:
  - /tasks/poc/e2e-demo.md
---

# Runbook apply path (v2, post-POC)

The governed write path from spec §5: action catalogue (parameter
schema + SQL template per engine + allowed environments + reversibility
flag), runbook-action files under `actions/pending/`, the DBA-group
merge gate, the manual apply CI job, and the applier (statement-at-a-
time execution with write-ahead audit, preflight target-identity check,
apply-time precondition re-evaluation, expiry, `resource_group`
serialization per endpoint).

First catalogue entries: `add_datafile`, `gather_stats`. Developed and
demoed entirely against the compose stack (oracle-free near-full
tablespace scenario) before any real credential exists.

Blast-radius rules from spec §5.1/§5.6: the applier executes only SQL
it re-renders from the catalogue template + schema-validated params
(`rendered_sql` in the action file is review-only and must match
byte-for-byte); prod apply credentials exist only on protected-branch
pipelines; target state is DB-enforced least privilege — the apply
account holds EXECUTE on catalogue procedures (`dba_actions` package /
SECURITY DEFINER functions) and no direct DDL.

## Deliverables

- [ ] Action catalogue format + validator; add_datafile and gather_stats templates with parameter caps (max size, identifier whitelist, existence check)
- [ ] Applier: preflight (identity, preconditions, expiry, already-applied), template-re-render + rendered_sql match check, statement-type gate + deny-list backstop, statement-at-a-time execution, write-ahead audit records
- [ ] DB-enforced action procedures: `dba_actions` package (Oracle) / SECURITY DEFINER functions (PG) with in-DB argument validation; apply account gets EXECUTE only — demoed in compose
- [ ] Role hardening in provisioning SQL: connection limits, statement/lock timeouts (PG), profile limits (Oracle)
- [ ] Negative tests: hand-edited rendered_sql refused; out-of-cap size refused; non-catalogue SQL refused by the DB itself under the apply account
- [ ] `dba_agent_audit` table DDL per engine + provisioning SQL for `dba_agent_apply`
- [ ] `.gitlab-ci.yml`: manual apply job, job name embeds action+target, `resource_group` per endpoint, runner-tag routing
- [ ] Agent gains "draft action MR" capability (GitLab token: write branch + open MR, not merge)
- [ ] End-to-end demo in compose: alert → diagnosis → action MR → merge → manual apply → tablespace grows → audit rows present → Slack thread updated
- [ ] Partial-apply drill: kill the applier mid-action, verify the audit shows the in-flight statement and re-run refuses until reviewed
