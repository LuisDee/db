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

## Deliverables

- [ ] Action catalogue format + validator; add_datafile and gather_stats templates
- [ ] Applier: preflight (identity, preconditions, expiry, already-applied), statement-at-a-time execution, write-ahead audit records
- [ ] `dba_agent_audit` table DDL per engine + provisioning SQL for `dba_agent_apply`
- [ ] `.gitlab-ci.yml`: manual apply job, job name embeds action+target, `resource_group` per endpoint, runner-tag routing
- [ ] Agent gains "draft action MR" capability (GitLab token: write branch + open MR, not merge)
- [ ] End-to-end demo in compose: alert → diagnosis → action MR → merge → manual apply → tablespace grows → audit rows present → Slack thread updated
- [ ] Partial-apply drill: kill the applier mid-action, verify the audit shows the in-flight statement and re-run refuses until reviewed
