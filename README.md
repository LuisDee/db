# db — DBA Agent

AI assistant for database operations across Postgres, Oracle (Standard
Edition), and QuestDB. It listens to the DBA alerts Slack channel,
debugs alerts with preset read-only queries, posts evidence-backed
diagnoses in-thread, reduces alert noise, and — behind a DBA-controlled
GitLab approval gate — proposes and applies operational runbook actions.

**Canonical spec:** [`docs/dba-agent-spec.md`](docs/dba-agent-spec.md) (v0.2).
Decision log: [`docs/dba-agent-direction.md`](docs/dba-agent-direction.md).
History: original spec v0.1 + adversarial review, also in `docs/`.

## Hard rules

- The agent never holds write credentials; writes happen only in a
  post-approval CI job under a separate identity — and that identity is
  not god: see `docs/apply-path-security-model.md`, including the
  go-live checklist that gates any production wiring.
- The LLM never authors diagnostic SQL — it selects and interprets
  DBA-reviewed playbook queries and action templates.
- No SSH to DB hosts; host facts come from the Check_MK API.
- Containers-first: the loop must pass in the local compose stack
  before touching any real host, credential, or channel.
- Oracle queries must be Standard-Edition- and license-clean (no
  AWR/ASH/`dba_hist_*`).

## Layout

- `docs/` — spec, review, decision log.
- `tasks/` — Structured Tasks work items (`depends_on` DAG, checklists
  as status, commit hashes as evidence). Start at `tasks/README.md`.
- `project-management/scripts/` — Structured Tasks tooling: context
  loader, task compliance gater, git branch guard.
- `src/`, `actions/`, `provisioning/`, `compose/` — arrive with the POC
  tasks (agent app, runbook-action catalogue, DB account provisioning
  SQL, local stack).

## Session ceremony (agents and humans)

1. `bash project-management/scripts/collect-structure-docs/collect-structure-docs.sh`
2. Pick an unblocked task in `tasks/` (all `depends_on` checked off).
3. Branch as `feat/<task-slug>`; verify with
   `bash project-management/scripts/check-branch-name/check-branch-name.sh`.
4. TDD; tick checklist items with commit evidence; run
   `bash project-management/scripts/check-task-compliance/check-task-compliance.sh`
   after any task-file change.
