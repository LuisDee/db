# Tasks — DBA agent POC

Work items for the DBA alerts agent, tracked as Structured Tasks:
markdown files with a `depends_on` DAG in frontmatter, checklists as the
only status, commit hashes as merge evidence. See
`docs/dba-agent-direction.md` for the why; see
`project-management/scripts/` for the compliance/branch-guard tooling.

## POC dependency graph

`depends_on` frontmatter is the source of truth; this diagram is kept
in sync with it, not the other way around. `[x]` = done and merged.

```
foundation/agent-skeleton [x]
 ├── foundation/endpoint-registry [x] ──┐
 ├── foundation/compose-stack [x] ──────┼── foundation/integration-test-infra [x]
 │                                      │        └── playbooks/playbook-framework [x]
 │                                      │             ├── playbooks/playbook-disk-space [x]      ─┐
 │                                      │             ├── playbooks/playbook-replication-lag      ─┤
 │                                      │             └── playbooks/playbook-tablespace-usage     ┤
 ├── listener/slack-listener                                                                      │
 └── listener/alert-classifier [x]                                                                │
      ├── triage/dedup-cooldown [x]                                                               │
      ├── triage/diagnosis-synthesis [x] (also needs playbook-framework [x]) ───────────────────┘
      └── digest/noise-digest

poc/v0-poc-ready ← compose-stack [x] + endpoint-registry [x]
              + playbook-framework [x]
     └── poc/e2e-demo ← diagnosis-synthesis [x] + dedup-cooldown [x]
              + compose-stack [x] + playbook-disk-space [x] + v0-poc-ready
              └── apply/runbook-apply-path (v2 write path, blocked on the demo)
```

Note: `listener/slack-listener` is NOT a dependency of anything on the
demo's critical path per its own frontmatter — `poc/e2e-demo` can be
satisfied by the alert-injector (already built in compose-stack)
driving the classifier/executor/synthesis chain directly, without a
live Socket Mode listener. Build `slack-listener` separately if/when a
genuinely live-Slack-driven demo (rather than script-driven) is wanted.

**The component tasks are done, but `poc/e2e-demo` is NOT "pure wiring
against finished parts."** A hands-on stress test of the live compose
stack (2026-07-08) found the parts have never run together against live
engines and the demo's own preconditions are unmet — the read path can't
connect (`dba_agent_ro` is provisioned nowhere) and `make up` exits
non-zero (postgres-replica never starts). Those newly-surfaced blockers
are tracked in `poc/v0-poc-ready.md`, now a dependency of `poc/e2e-demo`.

Everything except `apply/` is POC scope: prove the loop locally in
containers before anything touches a real host. Everything that is NOT
required for that demo — v1 real-infra wiring, the deferred hardening the
2026-07-08 review surfaced, v1.5 Jira, and the v2 write path — is
collected in `backlog/post-poc.md`.
