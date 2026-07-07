# Tasks — DBA agent POC

Work items for the DBA alerts agent, tracked as Structured Tasks:
markdown files with a `depends_on` DAG in frontmatter, checklists as the
only status, commit hashes as merge evidence. See
`docs/dba-agent-direction.md` for the why; see
`project-management/scripts/` for the compliance/branch-guard tooling.

## POC dependency graph

```
foundation/agent-skeleton
 ├── foundation/endpoint-registry
 │    └── playbooks/playbook-framework
 │         ├── playbooks/playbook-disk-space      ─┐
 │         ├── playbooks/playbook-replication-lag ─┤
 │         └── playbooks/playbook-tablespace-usage┤
 ├── foundation/compose-stack ──────(also feeds)──┘
 ├── listener/slack-listener
 │    └── triage/dedup-cooldown
 └── listener/alert-classifier
      ├── triage/diagnosis-synthesis (also needs playbook-framework)
      └── digest/noise-digest

poc/e2e-demo ← diagnosis-synthesis + dedup-cooldown + compose-stack
              + playbook-disk-space
     └── apply/runbook-apply-path (v2 write path, blocked on the demo)
```

Everything except `apply/` is POC scope: prove the loop locally in
containers before anything touches a real host. Further post-POC work
(live Jira, coverage advisor, capacity forecasting) gets registered as
new tasks when the POC demo passes.
